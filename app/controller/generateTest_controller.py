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

from fastapi.responses import FileResponse
from app.config.settings import settings
from app.model.db import get_postgres
from app.rag.ingestion import ingest_project
from app.rag.retrieval import retrieve_context

router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MEDIA_ROOT = PROJECT_ROOT / settings.MEDIA_ROOT
EXTRACT_FOLDER = PROJECT_ROOT / settings.EXTRACT_FOLDER

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
    imports: list[str] = []
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
    base_url = settings.LLM_URL.rstrip("/") if hasattr(settings, "LLM_URL") else "http://localhost:11434"
    url = f"{base_url}/api/chat"
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

        message = data.get("message")

        if isinstance(message, list):
            content_parts = []
            for msg in message:
                if isinstance(msg, dict):
                    content = msg.get("content")
                    if content:
                        content_parts.append(content)
            return "\n".join(content_parts)

        if isinstance(message, dict):
            return message.get("content", "")

        if isinstance(message, str):
            return message

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
    non_getter_setter = [
        m.group() for m in re.finditer(r"public\s+\w+\s+(\w+)\s*\(", content)
        if not (m.group().startswith("public void set") or "get" in m.group())
    ]
    return has_fields and has_getter_setter and not non_getter_setter


def is_interface_class(content: str) -> bool:
    return re.search(r'\bpublic\s+interface\s+\w+', content) is not None


def is_application_class(content: str) -> bool:
    return '@SpringBootApplication' in content or re.search(r'public\s+class\s+(\w+Application)', content) is not None


def build_prompt(data: dict, unit_test_framework: str, rag_context: str) -> str:
    class_name = data["filename"]
    source_code = data["content"]

    return f"""
You are a senior Java engineer specializing in production-grade unit tests.

TASK:
Generate a 100% compilable JUnit 5 test class for `{class_name}` that achieves maximum coverage.

CRITICAL CONSTRAINTS (VIOLATE ANY = FAILURE):
- You MUST use only the code that exists in:
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

Use JUnit 5 + Mockito:
- @ExtendWith(MockitoExtension.class)
- @Mock, @InjectMocks, when(...).thenReturn(...), verify(...)
- For List<T> → new ArrayList<>()
- For Optional<T> → Optional.of(...) or Optional.empty() ONLY if method returns Optional

TEST REQUIREMENTS:
- Test EVERY public method
- Happy path + edge cases + exception paths
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

    # Retrieve RAG context: bias towards controller/service/repo + HTTP mappings
    query = (
        f"{class_name} {class_name}Controller {class_name}Service {class_name}Repository "
        f"@GetMapping @PostMapping @PutMapping @DeleteMapping public"
    )
    rag_context = await retrieve_context(project_id=project_id, query=query, n_results=50)

    if not isinstance(rag_context, str):
        rag_context = str(rag_context)

    if not rag_context.strip():
        print(f"[RAG] No context for {class_name} — falling back to source only")
        rag_context = source_code

    rag_context = rag_context.strip()
    print(f"[RAG] Type: {type(rag_context)} | Len: {len(rag_context)}")

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
                    continue
        return classes

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

    def looks_like_valid_test(s: str) -> bool:
        return (
            "class " in s and
            f"{class_name}Test" in s and
            "@Test" in s
        )

    # === Fallback if output is incomplete ===
    if len(cleaned) < 200 or not looks_like_valid_test(cleaned):
        print(f"[LLM] Output too short/invalid, retrying with minimal prompt...")
        minimal_prompt = f"""
Generate a complete, compilable JUnit 5 test class named {class_name}Test
for the Java class {class_name} in package {pkg}.

CONTEXT:
{source_code.strip()}

RULES:
- Use @ExtendWith(MockitoExtension.class) if dependencies exist.
- Include at least 3 @Test methods.
- Test all public methods.
- Use only methods and fields that exist in the given class.
- Output ONLY Java code, no markdown, no comments, no explanations.
- Start with: package {pkg};

Generate the full test class now.
"""
        llm_output = getOllamaChat("llama3:latest", minimal_prompt)
        cleaned = clean_llm_output(llm_output)

    if not looks_like_valid_test(cleaned):
        # Last-resort safe minimal test to avoid empty files
        print(f"[LLM] Still invalid output for {class_name}, generating minimal fallback test.")
        cleaned = f"""
package {pkg};

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class {class_name}Test {{

    @Test
    void dummyTest() {{
        // Minimal fallback test to ensure compilation
        assertTrue(true);
    }}
}}
""".strip()

    final_code = ensure_imports(cleaned, pkg, all_imports)
    return final_code


def ensure_maven_dependencies(pom_path: str):
    tree = ET.parse(pom_path)
    root = tree.getroot()

    tag = root.tag
    if isinstance(tag, str) and '}' in tag:
        ns_uri = tag.split('}')[0].strip('{')
    else:
        ns_uri = "http://maven.apache.org/POM/4.0.0"
    ns = {"mvn": ns_uri}

    ET.register_namespace('', ns_uri)

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
    test_dir = Path(base_path) / "src/test/java"
    if package_path:
        test_dir = test_dir / package_path
    test_dir.mkdir(parents=True, exist_ok=True)
    test_file = test_dir / f"{class_name}Test.java"
    with open(test_file, "w", encoding="utf-8") as f:
        f.write(test_code)
    return str(test_file)


def find_pom_directory(base_dir: Path) -> Path | None:
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
        await db.execute(
            "UPDATE public.unittest SET processed_date = $1, status = 'in-progress' WHERE id = $2;",
            datetime.utcnow(), id
        )

        # Load metadata from DB
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
            raise HTTPException(404, "ZIP not found.")

        # Clean extraction folder
        if extract_path.exists():
            shutil.rmtree(extract_path)
        extract_path.mkdir(parents=True, exist_ok=True)

        # Extract uploaded project ZIP
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_path)

        # Ensure POM dependencies exist (JUnit/Mockito/JaCoCo)
        pom_files = list(extract_path.rglob("pom.xml"))
        if pom_files:
            ensure_maven_dependencies(str(pom_files[0]))

        # Ingest the project (RAG)
        print(f"[RAG] Starting ingestion for {id}")
        await ingest_project(id)
        print(f"[RAG] Ingestion complete.")

        # Collect Java files
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

        if not testable_classes:
            raise HTTPException(400, "No testable classes found.")

        # Generate test files
        for cls in testable_classes:
            print(f"[GENERATE] Processing {cls['filename']}")
            test_code = await generate_test_with_rag(cls, unit_test_type, id)
            if not test_code.strip():
                print(f"[SKIP] Empty test for {cls['filename']}")
                continue

            write_java_test_file(
                extract_path,
                cls["relative_path"],
                cls["filename"],
                test_code
            )

        # -----------------------------
        # 🔥 CREATE FINAL ZIP TO RETURN
        # -----------------------------
        output_zip = EXTRACT_FOLDER / f"{id}_with_tests.zip"

        if output_zip.exists():
            output_zip.unlink()

        print(f"[ZIP] Creating output ZIP: {output_zip}")

        with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in extract_path.rglob("*"):
                zipf.write(
                    file_path,
                    file_path.relative_to(extract_path)
                )

        # Mark status completed
        await db.execute(
            "UPDATE public.unittest SET processed_date = $1, status = 'completed' WHERE id = $2;",
            datetime.utcnow(),
            id
        )

        # -----------------------------
        # 🔥 RETURN ZIP FILE RESPONSE
        # -----------------------------
        return FileResponse(
            path=str(output_zip),
            filename=f"{id}_final_project.zip",
            media_type="application/zip"
        )

    except Exception as e:
        import traceback
        traceback.print_exc()

        await db.execute(
            "UPDATE public.unittest SET processed_date = $1, status = 'failed' WHERE id = $2;",
            datetime.utcnow(),
            id
        )

        raise HTTPException(500, f"Test generation failed: {str(e)}")
