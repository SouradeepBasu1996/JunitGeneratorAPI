import os
import zipfile
import shutil
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
import ollama
import subprocess
import requests
from app.model.db import get_postgres
import asyncpg  # type: ignore
import xml.etree.ElementTree as ET
from datetime import datetime


router = APIRouter()
MEDIA_ROOT = Path("uploads")
EXTRACT_FOLDER = Path("temp_extracted")
SUPPORTED_EXTENSIONS = {"java": ".java"}
REQUIRED_IMPORTS = [
    "import org.junit.jupiter.api.*;",
    "import org.junit.jupiter.api.extension.ExtendWith;",
    "import org.mockito.Mock;",
    "import org.mockito.InjectMocks;",
    "import org.mockito.junit.jupiter.MockitoExtension;",
    "import static org.mockito.ArgumentMatchers.*;",
    "import static org.mockito.Mockito.*;",
    "import java.util.*;",
    "import java.util.Optional;",
    "import java.util.ArrayList;",
    "import org.springframework.http.ResponseEntity;",
    "import org.springframework.http.HttpStatus;"
]

# Unit test generation templates
UNIT_TEST_TEMPLATES = {
    "junit": "Generate JUnit test cases with 90% coverage. Use structured assertions and follow jUnit best practices."
}

def sanitize(text: str) -> str:
    return re.sub(r"[^\x00-\x7F]+", "", text)


def clean_llm_output(raw_output: str) -> str:
    """
    Extracts the code content (inside triple backticks) from an LLM output.
    If no code block is found, returns the trimmed raw output.
    """
    # Match text inside triple backticks (handles language identifiers like ```java)
    match = re.search(r"```(?:\w+)?\n(.*?)```", raw_output, flags=re.DOTALL)

    if match:
        return match.group(1).strip()
    else:
        return raw_output.strip()


def parse_package(content: str) -> str:
    match = re.search(r'package\s+([\w\.]+);', content)
    return match.group(1) if match else ""


def extract_imports_from_source(source_content: str) -> list[str]:
    """Auto-extract package and classes from source → generate imports"""
    imports = []

    # Get package
    pkg_match = re.search(r'package\s+([\w\.]+);', source_content)
    pkg = pkg_match.group(1) if pkg_match else ''

    if not pkg:
        return imports

    # Find all public classes (entities/models/services)
    for line in source_content.splitlines():
        class_match = re.search(r'public\s+(class|interface)\s+(\w+)', line)
        if class_match:
            cls_name = class_match.group(2)
            imports.append(f"import {pkg}.{cls_name};")

    return list(set(imports))

def remove_imports_and_package(code: str) -> str:
    lines = code.splitlines(keepends=True)
    filtered = [line for line in lines if not line.strip().startswith(('package ', 'import '))]
    return ''.join(filtered)


def ensure_imports(code: str, pkg: str, required_imports: list[str]) -> str:
    # Collect existing imports
    existing = set()
    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith('import '):
            existing.add(stripped)

    # All imports: existing + required (no dups)
    all_imports = sorted(existing.union(required_imports))
    imports_str = '\n'.join(all_imports) + '\n\n'

    # Header
    pkg_decl = f"package {pkg};\n\n" if pkg else "\n\n"

    # Body (no old imports/package)
    body = remove_imports_and_package(code).lstrip()

    return pkg_decl + imports_str + body

def fix_llm_code(code: str, source_content: str) -> str:
    """Aggressively fix LLM-generated test code to compile 100%"""
    lines = code.splitlines(keepends=True)
    fixed = []
    in_test_method = False

    # --- Detect line ending ---
    line_ending = '\n'
    if lines and lines[0].endswith('\r\n'):
        line_ending = '\r\n'

    # Extract real method signatures from source
    method_signatures = {}
    for line in source_content.splitlines():
        m = re.search(r'public\s+([\w.<>\[\]]+)\s+(\w+)\s*\(', line)
        if m:
            ret_type, name = m.group(1), m.group(2)
            method_signatures[name] = ret_type

    for i, line in enumerate(lines):
        stripped = line.strip()
        indent = line[:len(line) - len(line.lstrip())]
        skip_line = False  # ← CRITICAL: Define here

        # Track test method scope
        if stripped.startswith("@Test") or stripped.startswith("@BeforeEach"):
            in_test_method = True
        if in_test_method and stripped == "}":
            in_test_method = False

        # 1. Fix: mockList(...) → List<X> list = new ArrayList<>();
        if "mockList(" in stripped:
            type_match = re.search(r'mockList\((\w+\.class)\)', stripped)
            if type_match:
                class_name = type_match.group(1).split('.')[-1].replace(".class", "")
                elem_type = class_name
                var_name = f"{elem_type.lower()}s"
                fixed.append(f"{indent}List<{elem_type}> {var_name} = new ArrayList<>();{line_ending}")
                skip_line = True

        # 2. Fix: .orElseThrow() on non-Optional → .orElse(new X())
        elif ".orElseThrow(" in stripped and "Optional" not in stripped:
            type_hint = "Object"
            if "findById" in stripped:
                for name, ret in method_signatures.items():
                    if name == "findById" and "Optional" in ret:
                        match = re.search(r'Optional<([^>]+)>', ret)
                        if match:
                            type_hint = match.group(1).split('.')[-1]
                        break
            line = re.sub(r'\.orElseThrow\([^)]*\)', f'.orElse(new {type_hint}())', line)

        # 3. Fix: when(void_method(...)).thenReturn(...) → thenAnswer
        elif "when(" in stripped and ").thenReturn(" in stripped:
            m = re.search(r'when\((.+?)\)\.thenReturn\(', stripped)
            if m:
                call = m.group(1)
                method_name = re.search(r'\.(\w+)\(', call)
                if method_name and method_name.group(1) in method_signatures:
                    ret_type = method_signatures[method_name.group(1)]
                    if ret_type == "void":
                        replacement = f".thenAnswer(invocation -> {{ invocation.callRealMethod(); return null; }}){indent}    // void method"
                        line = line.replace(".thenReturn(", replacement)

        # 4. Fix: return Long when Entity expected
        elif "thenReturn(1L)" in stripped or "thenReturn(1)" in stripped:
            for name, ret_type in method_signatures.items():
                if "Optional" in ret_type or "List" in ret_type or any(entity in ret_type for entity in ["Order", "User", "Product"]):
                    entity = re.search(r'(Order|User|Product|\w+)', ret_type).group(1)
                    line = line.replace("thenReturn(1L)", f"thenReturn(new {entity}())")
                    line = line.replace("thenReturn(1)", f"thenReturn(new {entity}())")

        # 5. Fix: withId(...) → setId(...)
        elif ".withId(" in stripped:
            line = line.replace(".withId(", ".setId(")

        # 6. Fix: deleteOrder → deleteById
        elif "deleteOrder(" in stripped:
            line = line.replace("deleteOrder(", "deleteById(")

        # --- 8. Fix List<class>, classs → List<Order>, orders ---
        elif re.search(r'List\s*<\s*class\s*>', line, re.IGNORECASE) or \
             re.search(r'\bclasss?\b', line, re.IGNORECASE):

            entity_type = "Order"
            for name, ret in method_signatures.items():
                if name == "findAll" and "List" in ret:
                    m = re.search(r'List<([^>]+)>', ret)
                    if m:
                        entity_type = m.group(1).split('.')[-1]
                    break

            line = re.sub(r'List\s*<\s*class\s*>', f'List<{entity_type}>', line, flags=re.IGNORECASE)
            line = re.sub(r'\bclasss?\b', f'{entity_type.lower()}s', line)

        # --- 7. Insert orders list if needed ---
        elif re.search(r'thenReturn\s*\(\s*orders\s*\)', line) and \
             not any(re.search(r'List<[^>]+>\s+\w*orders\b', l) for l in lines[:i]):

            return_type = "Order"
            for name, ret in method_signatures.items():
                if name == "findAll" and "List" in ret:
                    m = re.search(r'List<([^>]+)>', ret)
                    if m:
                        return_type = m.group(1).split('.')[-1]
                    break

            var_name = f"{return_type.lower()}s"
            fixed.append(f"{indent}List<{return_type}> {var_name} = new ArrayList<>();{line_ending}")
            fixed.append(f"{indent}{var_name}.add(new {return_type}());{line_ending}")
            skip_line = True

        # 9. Fix: @ExtendWith(MockitoExtension.orders)
        elif re.search(r'@ExtendWith\s*\([^)]*MockitoExtension\.orders', line):
            line = re.sub(r'MockitoExtension\.orders', 'MockitoExtension.class', line)

        # === 10. Fix: public orders OrderControllerTest { → public class OrderControllerTest { ===
        elif not in_test_method and re.search(r'public\s+.*?\s+(\w+Test)\s*\{', line):
            class_name_match = re.search(r'(\w+Test)', line)
            if class_name_match:
                class_name = class_name_match.group(1)
                # Rebuild line with correct indent and single {
                line = f"{indent}public class {class_name} {{" + line_ending

        # --- ONLY APPEND IF NOT SKIPPED ---
        if not skip_line:
            fixed.append(line)

    return ''.join(fixed)

def getOllamaChat(model: str, prompt: str) -> str:
    url = "http://localhost:11434/api/chat"
    message = {}
    message["role"] = "user"
    message["content"] = prompt
    messages = [message]
    options = {}
    options["temperature"] = 0
    options["seed"] = 77777
    params = {}
    params["model"] = model
    params['messages'] = messages
    params['options'] = options
    params['stream'] = False
    response = requests.post(url, json=params)
    return response.json()["message"]["content"]


def is_model_class(content: str) -> bool:
    """
    Heuristic to detect a Java model or DTO class with only properties (fields/getters/setters)
    and no business logic methods.
    Returns True for classes that:
      - have 'class' keyword
      - contain only fields and getter/setter methods
      - lack business logic methods (like void, return statements, or non-get/set methods)
    """

    # Must be a class declaration
    if "class " not in content:
        return False

    # Skip if there are methods likely to have business logic (`void`, `return`)
    if re.search(r"\bvoid\b", content) or re.search(r"\breturn\b", content):
        return False

    # Detect typical field declarations
    has_fields = bool(re.search(r"(private|public|protected)\s+\w+\s+\w+;", content))

    # Detect getter/setter methods (Java pattern)
    has_getter_setter = bool(re.search(r"public\s+\w+\s+get\w+\s*\(", content)) or \
                        bool(re.search(r"public\s+void\s+set\w+\s*\(", content))

    # Try to exclude classes with methods other than getters/setters
    non_getter_setter_methods = [
        m.group() for m in re.finditer(r"public\s+\w+\s+(\w+)\s*\(", content)
        if not (m.group().startswith("public void set") or m.group().startswith("public") and "get" in m.group())
    ]
    # If there are any non-getter/setter methods, not a pure DTO/model
    if non_getter_setter_methods:
        return False

    # If it has fields and only getter/setter methods, consider a model class
    return has_fields and has_getter_setter

def is_interface_class(content: str) -> bool:
    # look for 'interface' keyword in class declaration line, ignoring comments
    # A simple heuristic:
    pattern = r'\bpublic\s+interface\s+\w+'
    return re.search(pattern, content) is not None


def is_application_class(content: str) -> bool:
    """
    Detect if given Java source is a Spring Boot Application class,
    typically annotated with @SpringBootApplication or class name ends with 'Application'.
    """
    # Check for annotation
    if '@SpringBootApplication' in content:
        return True

    # Extract first public class name and check if it ends with Application
    match = re.search(r'public\s+class\s+(\w+)', content)
    if match:
        class_name = match.group(1)
        if class_name.endswith('Application'):
            return True
    return False


def build_prompt(data: dict, unit_test_framework: str) -> str:
    print(f"data: {data}")
    print(f"unit_test_framework: {unit_test_framework}")
    return f"""
        You are an expert Java developer focused on writing high-quality and testable unit tests.

        🎯 Your Goal:
        Generate fully **compilable, framework-specific, high-coverage** Java unit test code for the given class. The test code should directly build and pass in a Maven project using JUnit 5 **without any manual fixes or missing dependencies**.

        📂 Input Source Code:
        {data['content']}

        🧪 Test Framework:
        Strictly use `{unit_test_framework}` for unit testing (JUnit 5 with Mockito for mocks).

        ⚠️ Framework & Library Rules:
        - Use JUnit 5 annotations: `@Test`, `@BeforeEach`, `@AfterEach`, `@ExtendWith(MockitoExtension.class)`.
        - Use assertions from `org.junit.jupiter.api.Assertions`.
        - Use Mockito for mocking (`@Mock`, `@InjectMocks`, `Mockito.when()`, `Mockito.verify()`, etc).
        - Add any required imports (e.g., `org.mockito.Mock`, `org.mockito.InjectMocks`, `org.mockito.junit.jupiter.MockitoExtension`).
        - **Explicitly import all classes used in your test code, including**:
            - **Spring Framework classes like  `org.springframework.http.ResponseEntity`**
            - **Mockito JUnit extension `org.mockito.junit.jupiter.MockitoExtension`**
            - Other Java and project-specific imports necessary for compilation.
        - Do not omit any import; all imports needed for compilation must be included.
        - **Include all necessary Java imports for used types such as:
            java.util.List, java.util.Optional, and org.springframework.http.ResponseEntity for all relevant classes**

        - NEVER use invalid Mokito mocking like "mockList()" use "mock()" instead if required
        - **Only call `.orElseThrow()` method on `Optional` objects.**
        - Avoid calling `orElseThrow` on variables of other types such as `String`.
        - **Always call `.orElseThrow()` only on `Optional` objects**. Do not call it on `String`, `List`, or any other type.
        - Do not call or generate code for any method that does not exist in the source code or is invalid.
        - Explicitly, avoid using `mockList()` or any other non-standard or unsupported Mockito methods. Use `Mockito.mock(List.class)` or instantiate real lists.
        - Do not call any service methods that are not defined in the input source code. Verify method existence before generating calls.
        - NEVER use `mockList()`. Use `new ArrayList<>()` instead.
        - NEVER call `.orElseThrow()` on `String`, `Long`, or non-`Optional`.
        - Only mock methods that exist in the source class.
        - If a method returns `Order`, do not return `1L` or `Long`.
        - For ID-based lookup, use: `Optional.of(new Order())` or `Optional.empty()`.

        ✅ Testing Scope:
        1. Only generate unit tests for:
            - Controller classes
            - Service classes

        2. Strictly exclude:
            - DTOs
            - Simple model/POJO classes (with only fields and getters/setters)
            - Interfaces
            - Abstract classes
            - Static utility/helper classes

        📈 Code Coverage Requirements:
            - Aim for **90%+ line and branch coverage**
            - Thoroughly test all public methods, including:
                - Normal (happy path) scenarios
                - Edge cases (null, empty collections, boundary values)
                - Error and exception scenarios
                - All logical branches (`if`, `else`, `switch`, `try/catch`)

        **Constraints** :
            - Instead of asserting whole ResponseEntity, assert the body or status code explicitly.
            - Use : assertEquals(expectedBody, response.getBody())
            - Avoid: assertEquals(expectedResponseEntity, response)
            - Do not generate complex or nested generic type equality checks that cause type incompatibility.
            - Make tests maintainable and easy to understand.
            - Do not assign void method calls to variables. If a method returns void, simply call it without assignment.
            - Respect the method signatures of the input source code exactly. If the method returns void, do not expect a return value.
            - Generate only compilable and logically correct code. Do not introduce false assumptions about method return types.
            - Verify method behaviors through mocks or side effects, not via invalid return value assignments.
            - Always include **complete, correct, and necessary import statements** for all classes used, such as `java.util.List`, `java.util.Optional`, `org.springframework.http.ResponseEntity`, and Mockito classes.
            - Do not omit or generate incomplete import statements.
            - Ensure import statements are valid and follow Java syntax.
            
        🧪 Test Code Structure Requirements:
            - Start with all necessary Java `import` statements.
            - Use correct package structure for test classes (matching source).
            - Use descriptive test method names formatted as `methodName_expectedOutcome_scenario`.
            - If the class requires dependency injection, use proper Mockito mocks and inject them into the constructor or fields.
            - Only mock dependencies declared in the input source. Do not add mocks for dependencies not present in source.
            - Use concrete assertions (`assertEquals`, `assertNotNull`, `assertThrows`, etc).
            - Test must be independent and compilable.

        🚫 Output Constraints:
            - Output **only valid, raw Java unit test code**.
            - Do not include summaries, markdown, explanations, or repeated input.
            - No TODOs, comments, or unnecessary whitespace.
            - Do not duplicate or invent classes, methods, or dependencies.

        🔧 Target Runtime: Java 17+, JUnit 5, Mockito
    """


def generate_test_files(data: dict, unit_test_framework: str) -> str:
    """
    Generates Java unit test code by sending a class and testing framework to your LLM.
    - data: dictionary containing class metadata, especially content key for code
    - unit_test_framework: expected to be 'junit' or 'JUnit 5'
    """
    prompt = build_prompt(data, unit_test_framework)
    print("=====generate_test_files--- LLM call====================")
    # Use your preferred Ollama model name
    llm_test_code = getOllamaChat("llama3:latest", prompt).strip()
    return llm_test_code


def ensure_maven_dependencies(pom_path: str):
    """
    Checks and inserts JUnit 5, Mockito core, Mockito JUnit Jupiter, and JaCoCo in a Maven pom.xml file if missing,
    with appropriate versions and scopes.
    """
    ET.register_namespace('', "http://maven.apache.org/POM/4.0.0")
    tree = ET.parse(pom_path)
    root = tree.getroot()
    ns = {"mvn": root.tag.split('}')[0].strip('{')}

    # 1. Ensure <dependencies> exists
    deps = root.find("mvn:dependencies", ns)
    if deps is None:
        deps = ET.SubElement(root, "dependencies")

    def has_dep(group_id, artifact_id):
        for dep in deps.findall("mvn:dependency", ns):
            if dep.find("mvn:groupId", ns) is not None and \
               dep.find("mvn:groupId", ns).text == group_id and \
               dep.find("mvn:artifactId", ns) is not None and \
               dep.find("mvn:artifactId", ns).text == artifact_id:
                return True
        return False

    # Required dependencies with versions/scopes
    dep_list = [
        {"groupId": "org.junit.jupiter", "artifactId": "junit-jupiter", "version": "5.9.3", "scope": "test"},
        {"groupId": "org.mockito", "artifactId": "mockito-core", "version": "5.2.0", "scope": "test"},
        {"groupId": "org.mockito", "artifactId": "mockito-junit-jupiter", "version": "5.2.0", "scope": "test"},
    ]

    for depinfo in dep_list:
        if not has_dep(depinfo["groupId"], depinfo["artifactId"]):
            dep = ET.SubElement(deps, "dependency")
            for k in ["groupId", "artifactId", "version", "scope"]:
                if k in depinfo:
                    child = ET.SubElement(dep, k)
                    child.text = depinfo[k]

    # 2. Ensure JaCoCo plugin with full config
    build_node = root.find("mvn:build", ns)
    if build_node is None:
        build_node = ET.SubElement(root, "build")
    plugins_node = build_node.find("mvn:plugins", ns)
    if plugins_node is None:
        plugins_node = ET.SubElement(build_node, "plugins")
    jacoco_plugin = None
    for p in plugins_node.findall("mvn:plugin", ns):
        artifact = p.find("mvn:artifactId", ns)
        if artifact is not None and artifact.text == "jacoco-maven-plugin":
            jacoco_plugin = p
            break
    if jacoco_plugin is None:
        jacoco_plugin = ET.SubElement(plugins_node, "plugin")
        ET.SubElement(jacoco_plugin, "groupId").text = "org.jacoco"
        ET.SubElement(jacoco_plugin, "artifactId").text = "jacoco-maven-plugin"
        ET.SubElement(jacoco_plugin, "version").text = "0.8.8"

        executions = ET.SubElement(jacoco_plugin, "executions")

        prepare = ET.SubElement(executions, "execution")
        ET.SubElement(prepare, "id").text = "prepare-agent"
        goals = ET.SubElement(prepare, "goals")
        goal_prepare = ET.SubElement(goals, "goal")
        goal_prepare.text = "prepare-agent"

        report = ET.SubElement(executions, "execution")
        ET.SubElement(report, "id").text = "report"
        ET.SubElement(report, "phase").text = "test"
        goals = ET.SubElement(report, "goals")
        goal_report = ET.SubElement(goals, "goal")
        goal_report.text = "report"

    tree.write(pom_path, encoding="utf-8", xml_declaration=True)

def write_java_test_file(base_path, package_path, class_name, test_code):
    """
    Writes the test code into src/test/java/{package_path}/Test_{class_name}.java
    """
    test_dir = Path(base_path) / "src/test/java" / package_path
    test_dir.mkdir(parents=True, exist_ok=True)
    test_file = test_dir / f"{class_name}Test.java"
    with open(test_file, "w", encoding="utf-8") as f:
        f.write(test_code)
    return str(test_file)

def find_pom_directory(base_dir: Path) -> Path:
    for root, dirs, files in os.walk(base_dir):
        if "pom.xml" in files:
            return Path(root)
    return None

def run_maven_tests(project_path):
    """
    Runs 'mvn clean test' and returns coverage path and success/failure information.
    """
    try:
        proc = subprocess.run(
            ["mvn", "clean", "test"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=300
        )
        coverage_report = Path(project_path) / "target/site/jacoco/index.html"
        result = {
            "success": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "coverage_report": str(coverage_report) if coverage_report.exists() else None
        }
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/generate_java_tests/")
async def generate_java_tests(id: str = Query(...)):
    db = await get_postgres()

    try:
        # Mark job as in-progress
        await db.execute(
            "UPDATE public.unittest SET processed_date = $1, status = 'in-progress' WHERE id = $2;",
            datetime.utcnow(), id
        )

        # Fetch project metadata
        project_data = await db.fetchrow(
            "SELECT project_type, unit_test_type FROM public.unittest WHERE id = $1",
            id
        )
        if not project_data:
            raise HTTPException(404, "Project record not found in DB.")
        project_type, unit_test_type = project_data

        # Locate uploaded ZIP file
        zip_path = MEDIA_ROOT / "files" / f"{id}.zip"
        extract_path = EXTRACT_FOLDER / id
        if not zip_path.exists():
            raise HTTPException(404, "Uploaded zip file not found.")

        # Clean and prepare extraction folder
        if extract_path.exists():
            shutil.rmtree(extract_path)
        extract_path.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_path)

        # Check and patch pom.xml for dependencies
        found_pom = list(extract_path.rglob("pom.xml"))
        if not found_pom:
            raise HTTPException(400, "pom.xml not found in uploaded project.")
        pom_path = found_pom[0]
        ensure_maven_dependencies(str(pom_path))

        # Scan for .java source files, filter valid for test generation
        all_java_files = list(extract_path.rglob("*.java"))
        testable_classes = []
        for java_file in all_java_files:
            content = sanitize(java_file.read_text(encoding="utf-8"))
            if is_model_class(content):
                continue
            if is_interface_class(content):
                continue
            if is_application_class(content):
                continue
            # Parse package from file (if present)
            match = re.search(r'package\s+([\w.]+);', content)
            package_path = match.group(1).replace('.', '/') if match else ""
            testable_classes.append({
                "filename": java_file.stem,
                "relative_path": package_path,
                "content": content,
            })

        if not testable_classes:
            raise HTTPException(400, "No valid Java classes found for testing.")

        # LLM test generation and test file writing
        written_files = []
        for file_data in testable_classes:
            test_code = generate_test_files(file_data, unit_test_type)
            cleaned_code = clean_llm_output(test_code)

            # FIX 1: Auto-extract + inject imports/package
            pkg = parse_package(file_data["content"])
            entity_imports = extract_imports_from_source(file_data["content"])
            all_required = REQUIRED_IMPORTS + entity_imports
            imported_code = ensure_imports(cleaned_code, pkg, all_required)

            # FIX 2: Patch LLM logic bugs
            final_code = fix_llm_code(imported_code, file_data["content"])

            test_path = write_java_test_file(
                extract_path, file_data["relative_path"], file_data["filename"], final_code
            )
            written_files.append(str(test_path))

        # Run Maven tests and collect coverage info
        pom_dir = find_pom_directory(extract_path)
        if pom_dir is None:
            raise HTTPException(400, "pom.xml folder not found for Maven build.")
        coverage_result = run_maven_tests(str(pom_dir))
        status = "completed" if coverage_result["success"] else "failed"

        # Update DB status/post-run
        await db.execute(
            "UPDATE public.unittest SET processed_date = $1, status = $2 WHERE id = $3;",
            datetime.utcnow(), status, id
        )

        # Provide result
        return {
            "status": status,
            "test_files": written_files,
            "coverage_report": coverage_result.get("coverage_report"),
            "maven_stdout": coverage_result.get("stdout"),
            "maven_stderr": coverage_result.get("stderr"),
        }

    except HTTPException as e:
        await db.execute(
            "UPDATE public.unittest SET processed_date = $1, status = 'failed' WHERE id = $2;",
            datetime.utcnow(), id
        )
        raise e

    except Exception as e:
        await db.execute(
            "UPDATE public.unittest SET processed_date = $1, status = 'failed' WHERE id = $2;",
            datetime.utcnow(), id
        )
        raise HTTPException(500, f"Java test generation failed: {str(e)}")

def clean_autotest_files(auto_tests_path: str):
    for root, _, files in os.walk(auto_tests_path):
        for file in files:
            if file.endswith(".cs") and "AssemblyAttributes" not in file:
                file_path = os.path.join(root, file)

                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()

                cleaned_lines = []
                in_code = False
                brace_count = 0

                for line in lines:
                    if line.strip().startswith("```"):
                        continue
                    # Always include using directives
                    if line.strip().startswith("using "):
                        cleaned_lines.append(line)
                        continue
                    # Start including code after namespace/class declaration
                    if not in_code and (
                            "namespace " in line or "class " in line or "public " in line or "private " in line):
                        in_code = True

                    if in_code:
                        cleaned_lines.append(line)
                        brace_count += line.count("{")
                        brace_count -= line.count("}")
                        # Continue till all braces are closed
                        if brace_count <= 0 and "}" in line.strip():
                            break

                with open(file_path, "w", encoding="utf-8") as f:
                    f.writelines(cleaned_lines)


def run_coverage(id: str = Query(...)):
    try:
        base_path = os.path.join("temp_extracted", id)
        print(f'base_path:{base_path}')

        if not os.path.exists(base_path):
            raise HTTPException(status_code=404, detail="Project ID folder not found.")

        sln_file = f"{id}.sln"
        sln_path = os.path.join(base_path, sln_file)

        if not os.path.exists(sln_path):
            subprocess.run(["dotnet", "new", "sln", "-n", id], cwd=base_path, check=True)

        original_proj_path = None
        for root, _, files in os.walk(base_path):
            for file in files:
                if file.endswith(".csproj") and "AutoTests" not in root:
                    original_proj_path = os.path.relpath(os.path.join(root, file), base_path)
                    break

            if original_proj_path:
                break

        if not original_proj_path:
            raise HTTPException(status_code=404, detail="Original .csproj not found.")

        autotests_csproj = os.path.relpath(os.path.join(base_path, "AutoTests", "AutoTests.csproj"), base_path)
        if not os.path.exists(os.path.join(base_path, autotests_csproj)):
            raise HTTPException(status_code=404, detail="AutoTests.csproj not found.")

        sln_projects = subprocess.run(["dotnet", "sln", sln_file, "list"], cwd=base_path, capture_output=True,
                                      text=True).stdout
        if original_proj_path not in sln_projects:
            subprocess.run(["dotnet", "sln", sln_file, "add", original_proj_path], cwd=base_path, check=True)

        if autotests_csproj not in sln_projects:
            subprocess.run(["dotnet", "sln", sln_file, "add", autotests_csproj], cwd=base_path, check=True)

        auto_tests_path = os.path.join(base_path, "AutoTests")
        # clean_autotest_files(auto_tests_path)

        test_project_path = os.path.abspath(base_path)
        print(f'test_project_path:{test_project_path}')
        test_project_dir = os.path.dirname(test_project_path)
        print(f'test_project_dir:{test_project_dir}')
        coverage_output_dir = os.path.join(test_project_path, "coverage_report")
        print(f"coverage_output_dir:{coverage_output_dir}")

        if not os.path.exists(test_project_path):
            raise HTTPException(status_code=400, detail=f"Test project not found: {test_project_path}")

        # Step 1: dotnet clean
        try:
            clean_result = subprocess.run(
                ["dotnet", "clean", test_project_path],
                cwd=test_project_dir,
                capture_output=True,
                text=True
            )
            print("Clean STDOUT:", clean_result.stdout)
            print("Clean STDERR:", clean_result.stderr)
            if clean_result.returncode != 0:
                raise HTTPException(status_code=500, detail="dotnet clean failed")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        # Step 2: dotnet restore
        try:
            restore_result = subprocess.run(
                ["dotnet", "restore", test_project_path],
                cwd=test_project_dir,
                capture_output=True,
                text=True
            )
            print("Restore STDOUT:", restore_result.stdout)
            print("Restore STDERR:", restore_result.stderr)
            if restore_result.returncode != 0:
                raise HTTPException(status_code=500, detail="dotnet restore failed")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        # Step 3: dotnet build
        try:
            build_result = subprocess.run(
                ["dotnet", "build", test_project_path],
                cwd=test_project_dir,
                capture_output=True,
                text=True
            )
            print("Build STDOUT:", build_result.stdout)
            print("Build STDERR:", build_result.stderr)
            if build_result.returncode != 0:
                raise HTTPException(status_code=500, detail="dotnet build failed")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        # Step 4: Write runsettings
        try:
            runsettings_path = os.path.join(test_project_path, "cover.runsettings")
            with open(runsettings_path, "w", encoding="utf-8") as f:
                f.write("""<?xml version="1.0" encoding="utf-8"?>
            <RunSettings>
            <DataCollectionRunSettings>
                <DataCollectors>
                <DataCollector friendlyName="XPlat Code Coverage">
                    <Configuration>
                    <Format>cobertura</Format>
                    <IncludeTestAssembly>true</IncludeTestAssembly>
                    <ExcludeByFile>
                        <File>AutoTests/Program.cs</File>
                        <File>AutoTests/Models/*.cs</File>
                        <File>AutoTests/DTOs/*.cs</File>
                    </ExcludeByFile>
                    </Configuration>
                </DataCollector>
                </DataCollectors>
            </DataCollectionRunSettings>
            </RunSettings>""")

            # Run test
            test_result = subprocess.run([
                "dotnet", "test", test_project_path,
                "--collect:XPlat Code Coverage",
                "--settings", "cover.runsettings",
                "--results-directory", "coverage_report"
            ],
                cwd=test_project_path,
                check=True)

            print("Test STDOUT:", test_result.stdout)
            print("Test STDERR:", test_result.stderr)
            if test_result.returncode != 0:
                raise HTTPException(status_code=500, detail="dotnet test failed")

            print(f"XML path:{coverage_output_dir}")
            print(f"GUID folders inside coverage_report folder:{os.listdir(coverage_output_dir)}")

            # STEP 5: List all GUID-named subfolders
            guid_folders = [
                name for name in os.listdir(coverage_output_dir)
                if os.path.isdir(os.path.join(coverage_output_dir, name))
                   and len(name) >= 32 and "-" in name  # crude GUID check
            ]
            print(f"guid_folders:{guid_folders}")

            # STEP 6: Capture the first (or latest) GUID folder
            if guid_folders:
                print("Inside guid_folders")
                guid_folders.sort(key=lambda x: os.path.getmtime(os.path.join(coverage_output_dir, x)), reverse=True)
                guid_folder = guid_folders[0]
                full_guid_path = os.path.join(coverage_output_dir, guid_folder)
                print("✅ Found GUID folder:", full_guid_path)
            else:
                print("❌ No GUID folder found in:", coverage_output_dir)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        # Step 7: HTML report via ReportGenerator
        try:
            coverage_xml_path = os.path.join(full_guid_path, "coverage.cobertura.xml")
            html_output_dir = os.path.join(test_project_path, "coverage_html")
            print(f"coverage_xml_path:{coverage_xml_path}")
            print(f"html_output_dir:{html_output_dir}")

            html_result = subprocess.run(
                [
                    "reportgenerator",
                    f"-reports:{coverage_xml_path}",
                    f"-targetdir:{html_output_dir}",
                    "-reporttypes:Html"
                ],
                capture_output=True,
                text=True
            )
            print("ReportGen STDOUT:", html_result.stdout)
            print("ReportGen STDERR:", html_result.stderr)
            if html_result.returncode != 0:
                raise HTTPException(status_code=500, detail="ReportGenerator failed")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        return {
            "status": "Success",
            "xml_report_path": coverage_xml_path,
            "html_report_dir": coverage_output_dir,
            "dotnet_test_output": test_result.stdout
        }

    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Command execution failed",
                "command": e.cmd,
                "stdout": e.stdout,
                "stderr": e.stderr
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))