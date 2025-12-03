# app/rag/ingestion.py
from pathlib import Path
import shutil
import zipfile
import javalang
import chromadb
from chromadb.utils import embedding_functions
from tqdm import tqdm
import uuid
import httpx
import asyncio
from typing import List, Dict, Any
from app.config.settings import settings

# === CONFIG ===
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_NAME = settings.EMBEDDING_MODEL
EMBED_DIM = settings.EMBEDDING_DIM
BATCH_SIZE = settings.EMBED_BATCH_SIZE
OLLAMA_URL = settings.LLM_URL.rstrip("/")  # just in case
EMBED_TIMEOUT = settings.EMBED_TIMEOUT

MEDIA_ROOT = PROJECT_ROOT / settings.MEDIA_ROOT
EXTRACT_FOLDER = PROJECT_ROOT / settings.EXTRACT_FOLDER
CHROMA_PATH = PROJECT_ROOT / settings.CHROMA_PATH
CHROMA_COLLECTION = settings.CHROMA_COLLECTION

if getattr(settings, "AUTO_CREATE_DIRECTORIES", False):
    MEDIA_ROOT.mkdir(exist_ok=True, parents=True)
    EXTRACT_FOLDER.mkdir(exist_ok=True, parents=True)
    CHROMA_PATH.mkdir(exist_ok=True, parents=True)

# === ChromaDB ===
client = chromadb.PersistentClient(path=str(CHROMA_PATH))
collection = client.get_or_create_collection(name=CHROMA_COLLECTION)


# === Ollama Embedding Function (SYNC, run in thread from async) ===
class OllamaEmbeddingFunction(embedding_functions.EmbeddingFunction):
    def __init__(self, model_name: str):
        self.model_name = model_name

    def __call__(self, texts: List[str]) -> List[List[float]]:
        """
        Synchronous, blocking HTTP calls to Ollama.
        We'll call this from async code via asyncio.to_thread().
        """
        embeddings: List[List[float]] = []
        with httpx.Client(timeout=EMBED_TIMEOUT) as client:
            for text in texts:
                payload = {"model": self.model_name, "prompt": text}
                try:
                    resp = client.post(f"{OLLAMA_URL}/api/embeddings", json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    emb = data.get("embedding")
                    if not emb:
                        raise ValueError("No 'embedding' field in embedding response")
                except Exception as e:
                    print(f"[Embedding Error] {e}")
                    emb = [0.0] * EMBED_DIM
                embeddings.append(emb)
        return embeddings


ollama_ef = OllamaEmbeddingFunction(MODEL_NAME)


# === Parse Java Code ===
def parse_java_code(code: str, file_path: str, project_id: str) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []

    # FULL CLASS FIRST
    try:
        tree = javalang.parse.parse(code)
        class_name = tree.types[0].name if tree.types else "Unknown"

        chunks.append({
            "id": str(uuid.uuid4()),
            "text": code.strip(),
            "metadata": {
                "project_id": project_id,
                "file_path": file_path,
                "type": "full_class",
                "name": class_name,
            }
        })

    except Exception as e:
        print(f"[Parse Error] {file_path}: {e}")
        return chunks

    lines = code.splitlines()

    # === Better method end-line resolution ===
    def find_method_end(start_idx: int) -> int:
        depth = 0
        for i in range(start_idx, len(lines)):
            if "{" in lines[i]:
                depth += lines[i].count("{")
            if "}" in lines[i]:
                depth -= lines[i].count("}")
            if depth <= 0:
                return i + 1
        return start_idx + 1

    # Method chunks
    for _, node in tree.filter(javalang.tree.MethodDeclaration):
        start_line = node.position.line - 1 if node.position else 0
        end_line = find_method_end(start_line)

        body = "\n".join(lines[start_line:end_line]).strip()
        if not body:
            continue

        chunks.append({
            "id": str(uuid.uuid4()),
            "text": body,
            "metadata": {
                "project_id": project_id,
                "file_path": file_path,
                "type": "method",
                "name": node.name,
                "start_line": start_line + 1,
                "end_line": end_line,
            }
        })

    return chunks


# === Extract ZIP ===
def extract_project_zip(project_id: str) -> Path:
    zip_path = MEDIA_ROOT / "files" / f"{project_id}.zip"
    extract_path = EXTRACT_FOLDER / project_id

    if not zip_path.exists():
        raise FileNotFoundError(f"ZIP not found: {zip_path}")

    if extract_path.exists():
        shutil.rmtree(extract_path)
    extract_path.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(extract_path)

    return extract_path


# === List Java Files ===
def list_java_files(extract_path: Path) -> List[Dict[str, str]]:
    files: List[Dict[str, str]] = []
    for f in extract_path.rglob("*.java"):
        try:
            files.append({
                "path": str(f.relative_to(extract_path)),
                "content": f.read_text(encoding="utf-8")
            })
        except Exception as e:
            print(f"[File Read Error] {f}: {e}")
    return files


# === INGESTION ===
async def ingest_project(project_id: str):
    print(f"[INGEST] Starting for project: {project_id}")

    extract_path = extract_project_zip(project_id)
    java_files = list_java_files(extract_path)

    all_chunks: List[Dict[str, Any]] = []
    for jf in java_files:
        chunks = parse_java_code(jf["content"], jf["path"], project_id)
        all_chunks.extend(chunks)

    print(f"[INGEST] Total chunks: {len(all_chunks)}")

    if not all_chunks:
        print("[INGEST] No chunks to embed")
        return

    texts = [c["text"] for c in all_chunks]
    ids = [c["id"] for c in all_chunks]
    metadatas = [c["metadata"] for c in all_chunks]

    print("[INGEST] Embedding...")
    for i in tqdm(range(0, len(texts), BATCH_SIZE), desc="Embedding"):
        batch_texts = texts[i:i + BATCH_SIZE]
        batch_ids = ids[i:i + BATCH_SIZE]
        batch_meta = metadatas[i:i + BATCH_SIZE]

        # run blocking embedding in a thread so FastAPI event loop is not blocked
        embeddings = await asyncio.to_thread(ollama_ef, batch_texts)

        collection.upsert(
            ids=batch_ids,
            embeddings=embeddings,
            documents=batch_texts,
            metadatas=batch_meta
        )

    print(f"[INGEST] Completed for project {project_id}")
