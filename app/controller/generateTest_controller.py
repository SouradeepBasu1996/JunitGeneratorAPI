# app/controller/generate_tests_controller.py
import os
import zipfile
import shutil
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
import requests
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime

from app.model.db import get_postgres
from app.rag.ingestion import ingest_project
from app.rag.retrieval import retrieve_context

router = APIRouter()
MEDIA_ROOT = Path("uploads")
EXTRACT_FOLDER = Path("temp_extracted")

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

def sanitize(text: str) -> str:
    return re.sub(r"[^\x00-\x7F]+", "", text)


def clean_llm_output(raw_output: any) -> str:
    # Step 1: Extract string from any structure
    if isinstance(raw_output, (list, tuple)):
        parts = []
        for item in raw_output:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("content", ""))
        raw_output = "\n".join(filter(None, parts))
    elif isinstance(raw_output, dict):
        raw_output = raw_output.get("content", "")
    elif not isinstance(raw_output, str):
        raw_output = str(raw_output)

    # Step 2: Extract code block
    match = re.search(r"```(?:java)?\s*(.*?)\s*```", raw_output, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Step 3: Clean raw output
    return raw_output.strip()

def parse_package(content: str) -> str:
    match = re.search(r'package\s+([\w\.]+);', content)
    return match.group(1) if match else ""

def extract_imports_from_source(source_content: str) -> list[str]:
    imports = []
    pkg_match = re.search(r'package\s+([\w\.]+);', source_content)
    pkg = pkg_match.group(1) if pkg_match else ''
    if not pkg:
        return imports
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
    existing = set()
    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith('import '):
            existing.add(stripped)
    all_imports = sorted(existing.union(required_imports))
    imports_str = '\n'.join(all_imports) + '\n\n'
    pkg_decl = f"package {pkg};\n\n" if pkg else "\n\n"
    body = remove_imports_and_package(code).lstrip()
    return pkg_decl + imports_str + body


def getOllamaChat(model: str, prompt: str) -> str:
    url = "http://localhost:11434/api/chat"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0, "seed": 77777}
    }
    try:
        response = requests.post(url, json=payload, timeout=300)
        response.raise_for_status()
        data = response.json()

        # --- EXTRACT CONTENT SAFELY ---
        message = data.get("message")

        # Case 1: message is a list of dicts (common in streaming or errors)
        if isinstance(message, list):
            content_parts = []
            for msg in message:
                if isinstance(msg, dict):
                    content = msg.get("content")
                    if content:
                        content_parts.append(content)
            return "\n".join(content_parts)

        # Case 2: message is a dict
        if isinstance(message, dict):
            return message.get("content", "")

        # Case 3: message is string (rare)
        if isinstance(message, str):
            return message

        # Case 4: fallback
        return str(message) if message else ""

    except Exception as e:
        print(f"[Ollama ERROR] {e}")
        print(f"[Response] {response.text if 'response' in locals() else 'N/A'}")
        return ""

def is_model_class(content: str) -> bool:
    if "class " not in content:
        return False
    if re.search(r"\bvoid\b", content) or re.search(r"\breturn\b", content):
        return False
    has_fields = bool(re.search(r"(private|public|protected)\s+\w+\s+\w+;", content))
    has_getter_setter = bool(re.search(r"public\s+\w+\s+get\w+\s*\(", content)) or \
                        bool(re.search(r"public\s+void\s+set\w+\s*\(", content))
    non_getter_setter = [m.group() for m in re.finditer(r"public\s+\w+\s+(\w+)\s*\(", content)
                         if not (m.group().startswith("public void set") or "get" in m.group())]
    return has_fields and has_getter_setter and not non_getter_setter

def is_interface_class(content: str) -> bool:
    return re.search(r'\bpublic\s+interface\s+\w+', content) is not None

def is_application_class(content: str) -> bool:
    return '@SpringBootApplication' in content or re.search(r'public\s+class\s+(\w+Application)', content) is not None

def build_prompt(data: dict, unit_test_framework: str, rag_context: str) -> str:
    """
    Builds a bullet-proof, hallucination-resistant prompt that forces the LLM
    to generate ONLY real, compile-ready JUnit 5 tests using the exact source
    code + RAG-retrieved context.
    """
    class_name = data["filename"]
    source_code = data["content"]

    return f"""
        You are a senior Java engineer specializing in production-grade unit tests.

        TASK:
        Generate a **100% compilable** JUnit 5 test class for `{class_name}` that achieves maximum coverage.

        CRITICAL CONSTRAINTS (VIOLATE ANY = FAILURE):
        - You MUST use **only** the code that exists in:
            1. TARGET SOURCE CODE below
            2. RAG CONTEXT below
        - NEVER invent methods, fields, parameters, return types, or classes.
        - If a method is not present in the source or RAG → do NOT call it.
        - If a return type is unknown → use only what is explicitly shown.

        TARGET CLASS: `{class_name}`

        TARGET SOURCE CODE (EXACT, DO NOT HALLUCINATE):
            {source_code.strip()}

        RAG CONTEXT (REAL IMPLEMENTATIONS FROM PROJECT - USE THESE):
            {rag_context.strip()}

        FRAMEWORK: {unit_test_framework}

            Use JUnit 5 + Mockito
            @ExtendWith(MockitoExtension.class)
            @WebMvcTest(controllers = {class_name}.class)  // only if it's a @RestController
            @Mock, @InjectMocks, when(...).thenReturn(...), verify(...)
            Assertions.* static imports
            For List<T> → new ArrayList<>()
            For Optional<T> → Optional.of(...) or Optional.empty() ONLY if method returns Optional
            NEVER use .orElseThrow() on non-Optional types
            NEVER use mockList(), mockMap(), etc.

            TEST REQUIREMENTS:
            - Test EVERY public method
            - Happy path + all edge cases + exception paths
            - Descriptive test names: shouldX_whenY_thenZ
            - Assert actual behavior (status codes, body, side effects)
            - For controllers: assert response.getBody(), not whole ResponseEntity

            OUTPUT RULES:
            - Output ONLY the pure Java test file
            - NO markdown, NO ```java, NO explanations, NO comments
            - Start directly with package declaration
            - Include ALL necessary imports
            - Exact package name matching the source
            - Class name: {class_name}Test

            Generate the test now.
        """


async def generate_test_with_rag(data: dict, unit_test_framework: str, project_id: str) -> str:
    class_name = data["filename"]
    source_code = data["content"]
    pkg = parse_package(source_code)

    # Retrieve RAG context
    query = f"Full implementation of {class_name} and all its dependencies, methods, return types, and related classes"
    rag_context = await retrieve_context(project_id=project_id, query=query, n_results=10)

    print(f"[RAG] Type: {type(rag_context)} | Len: {len(rag_context) if hasattr(rag_context, '__len__') else 'N/A'}")

    if not isinstance(rag_context, str):
        rag_context = str(rag_context)
    if not rag_context.strip():
        print(f"[RAG] No context for {class_name} — falling back to source only")
        rag_context = "/* No additional context found */"
    rag_context = rag_context.strip()

    # === Safe helper: Extract class names from RAG context ===
    def extract_classes_from_rag(text: str) -> set[str]:
        classes = set()
        patterns = [
            r'public\s+(class|interface)\s+(\w+)',
            r'@Entity.*?class\s+(\w+)',
            r'@Service.*?class\s+(\w+)',
            r'@Repository.*?class\s+(\w+)',
            r'@RestController.*?class\s+(\w+)',
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.DOTALL):
                try:
                    classes.add(match.group(2))
                except IndexError:
                    continue  # Skip malformed matches
        return classes

    # === Build imports safely ===
    rag_classes = extract_classes_from_rag(rag_context)
    source_imports = extract_imports_from_source(source_code)
    rag_imports = [f"import {pkg}.{cls};" for cls in rag_classes if cls != class_name]
    all_imports = list(set(REQUIRED_IMPORTS + source_imports + rag_imports))

    # === Generate test ===
    prompt = build_prompt(data, unit_test_framework, rag_context)
    print(f"[LLM] Generating test for {class_name}...")
    llm_output = getOllamaChat("llama3:latest", prompt)

    print(f"[DEBUG] LLM output type: {type(llm_output)}")
    print(f"[DEBUG] LLM output (first 300): {repr(llm_output)[:300]}")

    cleaned = clean_llm_output(llm_output)

    # === Fallback if output is incomplete ===
    if len(cleaned) < 200 or "class " not in cleaned:
        print(f"[LLM] Output too short, retrying with minimal prompt...")
        minimal_prompt = (
            f"Generate a complete JUnit 5 test for {class_name} using @WebMvcTest, @MockBean, and MockMvc. "
            f"Test all public endpoints. Use only real classes and methods from the project. "
            f"Output only pure Java code. No markdown. Start with package {pkg};"
        )
        llm_output = getOllamaChat("llama3:latest", minimal_prompt)
        cleaned = clean_llm_output(llm_output)

    # === Finalize with correct package and imports ===
    final_code = ensure_imports(cleaned, pkg, all_imports)

    return final_code

def ensure_maven_dependencies(pom_path: str):
    tree = ET.parse(pom_path)
    root = tree.getroot()  # ← This is the real root

    # --- FIX: root.tag might be malformed, so extract namespace safely ---
    tag = root.tag
    if isinstance(tag, str):
        ns_uri = tag.split('}')[0].strip('{') if '}' in tag else ""
    else:
        ns_uri = "http://maven.apache.org/POM/4.0.0"  # fallback
    ns = {"mvn": ns_uri}

    ET.register_namespace('', ns_uri)

    # 1. Ensure <dependencies>
    deps = root.find("mvn:dependencies", ns)
    if deps is None:
        deps = ET.SubElement(root, "dependencies")

    def has_dep(group_id, artifact_id):
        for dep in deps.findall("mvn:dependency", ns):
            gid = dep.find("mvn:groupId", ns)
            aid = dep.find("mvn:artifactId", ns)
            if gid is not None and gid.text == group_id and aid is not None and aid.text == artifact_id:
                return True
        return False

    # Add required deps
    required_deps = [
        {"groupId": "org.junit.jupiter", "artifactId": "junit-jupiter", "version": "5.9.3", "scope": "test"},
        {"groupId": "org.mockito", "artifactId": "mockito-core", "version": "5.2.0", "scope": "test"},
        {"groupId": "org.mockito", "artifactId": "mockito-junit-jupiter", "version": "5.2.0", "scope": "test"},
    ]

    for d in required_deps:
        if not has_dep(d["groupId"], d["artifactId"]):
            dep = ET.SubElement(deps, "dependency")
            for key in ["groupId", "artifactId", "version", "scope"]:
                if key in d:
                    elem = ET.SubElement(dep, key)
                    elem.text = d[key]

    # 2. Ensure JaCoCo plugin
    build = root.find("mvn:build", ns)
    if build is None:
        build = ET.SubElement(root, "build")
    plugins = build.find("mvn:plugins", ns)
    if plugins is None:
        plugins = ET.SubElement(build, "plugins")

    jacoco_exists = any(
        p.find("mvn:artifactId", ns) is not None and
        p.find("mvn:artifactId", ns).text == "jacoco-maven-plugin"
        for p in plugins.findall("mvn:plugin", ns)
    )

    if not jacoco_exists:
        plugin = ET.SubElement(plugins, "plugin")
        ET.SubElement(plugin, "groupId").text = "org.jacoco"
        ET.SubElement(plugin, "artifactId").text = "jacoco-maven-plugin"
        ET.SubElement(plugin, "version").text = "0.8.8"
        executions = ET.SubElement(plugin, "executions")

        for exec_id, phase, goal in [
            ("prepare-agent", None, "prepare-agent"),
            ("report", "test", "report")
        ]:
            exec_elem = ET.SubElement(executions, "execution")
            ET.SubElement(exec_elem, "id").text = exec_id
            if phase:
                ET.SubElement(exec_elem, "phase").text = phase
            goals = ET.SubElement(exec_elem, "goals")
            ET.SubElement(goals, "goal").text = goal

    tree.write(pom_path, encoding="utf-8", xml_declaration=True)

def write_java_test_file(base_path, package_path, class_name, test_code):
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
    try:
        proc = subprocess.run(
            ["mvn", "clean", "test"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=300
        )
        coverage_report = Path(project_path) / "target/site/jacoco/index.html"
        return {
            "success": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "coverage_report": str(coverage_report) if coverage_report.exists() else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/generate_tests/")
async def generate_java_tests(id: str = Query(...)):
    db = await get_postgres()
    try:
        # === YOUR ENTIRE CODE BELOW ===
        await db.execute(
            "UPDATE public.unittest SET processed_date = $1, status = 'in-progress' WHERE id = $2;",
            datetime.utcnow(), id
        )

        project_data = await db.fetchrow(
            "SELECT project_type, unit_test_type FROM public.unittest WHERE id = $1", id
        )
        if not project_data:
            raise HTTPException(404, "Project not found.")
        project_type, unit_test_type = project_data

        zip_path = MEDIA_ROOT / "files" / f"{id}.zip"
        extract_path = EXTRACT_FOLDER / id

        print(f"[DEBUG] ZIP path: {zip_path}")
        print(f"[DEBUG] Extract path: {extract_path}")

        if not zip_path.exists():
            print(f"[ERROR] ZIP not found: {zip_path}")
            raise HTTPException(404, "ZIP not found.")

        if extract_path.exists():
            shutil.rmtree(extract_path)
        extract_path.mkdir(parents=True, exist_ok=True)

        print(f"[DEBUG] Extracting ZIP...")
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_path)
        print(f"[DEBUG] Extracted to: {extract_path}")

        pom_files = list(extract_path.rglob("pom.xml"))
        print(f"[DEBUG] Found pom.xml: {pom_files}")
        if not pom_files:
            raise HTTPException(400, "pom.xml not found.")
        ensure_maven_dependencies(str(pom_files[0]))

        # === INGESTION WITH FULL TRACEBACK ===
        print(f"[RAG] Starting ingestion for {id}")
        try:
            await ingest_project(id)
            print(f"[RAG] Ingestion complete.")
        except Exception as e:
            import traceback
            print(f"[RAG INGESTION FAILED] {e}")
            traceback.print_exc()
            raise HTTPException(500, f"RAG ingestion failed: {str(e)}")

        # === REST OF YOUR CODE ===
        all_java_files = list(extract_path.rglob("*.java"))
        print(f"[DEBUG] Found {len(all_java_files)} .java files")

        testable_classes = []
        for java_file in all_java_files:
            content = sanitize(java_file.read_text(encoding="utf-8"))
            if is_model_class(content) or is_interface_class(content) or is_application_class(content):
                continue
            match = re.search(r'package\s+([\w.]+);', content)
            package_path = match.group(1).replace('.', '/') if match else ""
            testable_classes.append({
                "filename": java_file.stem,
                "relative_path": package_path,
                "content": content,
                "file_path": java_file
            })

        print(f"[DEBUG] Testable classes: {len(testable_classes)}")
        if not testable_classes:
            raise HTTPException(400, "No testable classes found.")

        written_files = []
        for cls in testable_classes:
            print(f"[GENERATE] Processing {cls['filename']}")
            test_code = await generate_test_with_rag(cls, unit_test_type, id)
            if not test_code.strip():
                print(f"[SKIP] Empty test for {cls['filename']}")
                continue
            test_path = write_java_test_file(
                extract_path, cls["relative_path"], cls["filename"], test_code
            )
            written_files.append(str(test_path))

        pom_dir = find_pom_directory(extract_path)
        if not pom_dir:
            raise HTTPException(400, "pom.xml directory not found.")
        coverage_result = run_maven_tests(str(pom_dir))
        status = "completed" if coverage_result["success"] else "failed"

        await db.execute(
            "UPDATE public.unittest SET processed_date = $1, status = $2 WHERE id = $3;",
            datetime.utcnow(), status, id
        )

        return {
            "status": status,
            "test_files": written_files,
            "coverage_report": coverage_result.get("coverage_report"),
            "maven_stdout": coverage_result.get("stdout"),
            "maven_stderr": coverage_result.get("stderr"),
        }

    except Exception as e:
        # === FINAL CATCH-ALL ===
        import traceback
        print(f"[FATAL ERROR] {e}")
        traceback.print_exc()
        await db.execute(
            "UPDATE public.unittest SET processed_date = $1, status = 'failed' WHERE id = $2;",
            datetime.utcnow(), id
        )
        raise HTTPException(500, f"Test generation failed: {str(e)}")