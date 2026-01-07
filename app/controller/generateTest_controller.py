# app/controller/generate_tests_controller.py
import os
import shutil
import zipfile
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

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
    "import org.springframework.http.ResponseEntity;",
    "import org.springframework.http.HttpStatus;"
]


def sanitize(text: str) -> str:
    return re.sub(r"[^\x00-\x7F]+", "", text)


def clean_llm_output(raw_output: any) -> str:
    if isinstance(raw_output, dict):
        raw_output = raw_output.get("content", "")
    elif not isinstance(raw_output, str):
        raw_output = str(raw_output)

    match = re.search(r"```(?:java)?\s*(.*?)\s*```", raw_output, re.DOTALL)
    if match:
        return match.group(1).strip()

    return raw_output.strip()


def parse_package(content: str) -> str:
    match = re.search(r'package\s+([\w\.]+);', content)
    return match.group(1) if match else ""


def ensure_imports(code: str, pkg: str) -> str:
    imports_str = "package " + pkg + ";\n\n" if pkg else ""
    imports_str += "\n".join(REQUIRED_IMPORTS) + "\n\n"

    body = re.sub(r'^(package|import).*$', '', code, flags=re.MULTILINE).lstrip()
    return imports_str + body


def getOllamaChat(model: str, prompt: str) -> str:
    base_url = settings.LLM_URL.rstrip("/") \
        if hasattr(settings, "LLM_URL") else "http://localhost:11434"

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

        if isinstance(message, dict):
            return message.get("content", "")
        if isinstance(message, str):
            return message
        return str(message) if message else ""

    except Exception as e:
        print(f"[Ollama ERROR] {e}")
        return ""


def build_prompt(data: dict, unit_test_framework: str, rag_context: str) -> str:
    class_name = data["filename"]
    source_code = data["content"]

    return f"""
You are a senior Java engineer specializing in JUnit 5 unit tests.

TASK:
Generate a fully compilable JUnit 5 test class for `{class_name}`.

CONSTRAINTS:
- Use ONLY methods and classes that exist in the source below or RAG context.
- Do NOT invent anything.

SOURCE CODE:
{source_code.strip()}

RAG CONTEXT:
{rag_context.strip()}

FRAMEWORK: {unit_test_framework}

OUTPUT ONLY JAVA CODE – NO MARKDOWN.
"""


async def generate_test_with_rag(data: dict, unit_test_framework: str, project_id: str) -> str:
    class_name = data["filename"]
    source_code = data["content"]

    rag_context = await retrieve_context(project_id=project_id,
                                         query=class_name,
                                         n_results=50)

    prompt = build_prompt(data, unit_test_framework, rag_context)

    llm_output = getOllamaChat("llama3:latest", prompt)
    cleaned = clean_llm_output(llm_output)

    final_code = ensure_imports(cleaned, parse_package(source_code))
    return final_code


@router.post("/generate_tests/")
async def generate_java_tests(id: str = Query(...)):
    db = await get_postgres()

    try:
        # 1> mark in progress
        await db.execute(
            "UPDATE public.unittest SET processed_date=$1, status='in-progress' WHERE id=$2;",
            datetime.utcnow(), id
        )

        # 2> fetch metadata
        project_data = await db.fetchrow(
            "SELECT project_type, unit_test_type FROM public.unittest WHERE id=$1;",
            id
        )

        if not project_data:
            raise HTTPException(404, "Project not found.")

        project_type, unit_test_type = project_data

        zip_path = MEDIA_ROOT / "files" / f"{id}.zip"
        extract_path = EXTRACT_FOLDER / id

        if not zip_path.exists():
            raise HTTPException(404, "ZIP not found.")

        # 3> extract project
        if extract_path.exists():
            shutil.rmtree(extract_path)

        extract_path.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_path)

        # 4> ingest to RAG
        await ingest_project(id)

        # 5> find java files
        all_java_files = list(extract_path.rglob("*.java"))

        testable_classes = []

        for java_file in all_java_files:
            content = sanitize(java_file.read_text(encoding="utf-8"))

            if "public class" not in content:
                continue

            pkg = parse_package(content)
            package_path = pkg.replace('.', '/') if pkg else ""

            testable_classes.append({
                "filename": java_file.stem,
                "relative_path": package_path,
                "content": content,
                "file_path": java_file
            })

        if not testable_classes:
            raise HTTPException(400, "No testable classes found.")

        generated_names: list[str] = []

        # 6> generate and store tests
        for cls in testable_classes:
            test_code = await generate_test_with_rag(
                cls, unit_test_type, id
            )

            cleaned = clean_llm_output(test_code)

            if not cleaned.strip():
                continue

            test_dir = Path("temp_extracted") / id / "src/test/java"
            test_dir.mkdir(parents=True, exist_ok=True)

            final_test_file = test_dir / f"{cls['filename']}Test.java"

            with open(final_test_file, "w", encoding="utf-8") as f:
                f.write(cleaned)

            generated_names.append(cls["filename"])

        # deduplicate once
        generated_names = list(set(generated_names))

        # 7> mark completed
        await db.execute(
            "UPDATE public.unittest SET processed_date=$1, status='completed' WHERE id=$2;",
            datetime.utcnow(), id
        )

        # 8> return structured JSON
        return {
            "status": "success",
            "id": id,
            "tests_generated": generated_names,
            "location": f"temp_extracted/{id}/src/test"
        }

    except Exception as e:
        await db.execute(
            "UPDATE public.unittest SET processed_date=$1, status='failed' WHERE id=$2;",
            datetime.utcnow(), id
        )

        raise HTTPException(500, f"Test generation failed: {str(e)}")
