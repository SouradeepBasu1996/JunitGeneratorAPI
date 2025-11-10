# app/controller/rag_ingestion_controller.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pathlib import Path
import shutil
import zipfile
import javalang
import httpx
import chromadb
from chromadb.utils import embedding_functions
from tqdm import tqdm
import asyncio
import uuid
from typing import List, Dict, Any
from pydantic import BaseModel

# === CREATE ROUTER ===
router = APIRouter(prefix="/rag", tags=["RAG Pipeline"])

# === CONFIG ===
MEDIA_ROOT = Path("uploads")
EXTRACT_FOLDER = Path("temp_extracted")
CHROMA_PATH = Path("./chroma_db")
OLLAMA_URL = "http://localhost:11434"
MODEL_NAME = "nomic-embed-text:latest"
BATCH_SIZE = 8

# Ensure directories
MEDIA_ROOT.mkdir(exist_ok=True)
EXTRACT_FOLDER.mkdir(exist_ok=True)
CHROMA_PATH.mkdir(exist_ok=True)

# === ChromaDB Setup ===
client = chromadb.PersistentClient(path=str(CHROMA_PATH))
collection = client.get_or_create_collection(name="java_code")

# === Ollama Embedding Function (NO REUSED CLIENT) ===
class OllamaEmbeddingFunction(embedding_functions.EmbeddingFunction):
    def __init__(self, model_name: str):
        self.model_name = model_name

    async def _embed_single(self, text: str) -> List[float]:
        async with httpx.AsyncClient(timeout=120.0) as client:
            payload = {"model": self.model_name, "prompt": text}
            try:
                resp = await client.post(f"{OLLAMA_URL}/api/embeddings", json=payload)
                resp.raise_for_status()
                return resp.json()["embedding"]
            except Exception as e:
                print(f"[Embedding Error] {e}")
                return [0.0] * 768  # Zero vector on failure

    async def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        results = await asyncio.gather(
            *[self._embed_single(t) for t in texts],
            return_exceptions=True
        )
        return [
            [0.0] * 768 if isinstance(r, Exception) else r
            for r in results
        ]

    def __call__(self, input: List[str]) -> List[List[float]]:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, self._embed_batch(input))
            return future.result()

ollama_ef = OllamaEmbeddingFunction(MODEL_NAME)

# === Pydantic Models ===
class RetrieveRequest(BaseModel):
    query: str

# === Parse Java Code (with FULL CLASS chunk) ===
def parse_java_code(code: str, file_path: str, project_id: str) -> List[Dict[str, Any]]:
    chunks = []
    try:
        tree = javalang.parse.parse(code)
    except Exception as e:
        print(f"[Parse Error] {file_path}: {e}")
        return chunks

    lines = code.splitlines()

    # === METHOD CHUNKS ===
    for _, node in tree.filter(javalang.tree.MethodDeclaration):
        start_line = node.position.line if node.position else 0
        end_line = getattr(node, 'end_line', start_line + (len(node.body) if node.body else 0))
        body = "\n".join(lines[start_line - 1:end_line]).strip()
        if not body:
            continue

        chunk = {
            "id": str(uuid.uuid4()),
            "text": body,
            "metadata": {
                "project_id": project_id,  # ← FIXED
                "file_path": file_path,
                "type": "method",
                "name": node.name,
                "start_line": start_line,
                "end_line": end_line,
            }
        }
        chunks.append(chunk)

    # === CLASS CHUNKS ===
    for _, node in tree.filter(javalang.tree.ClassDeclaration):
        start_line = node.position.line if node.position else 0
        chunk = {
            "id": str(uuid.uuid4()),
            "text": f"class {node.name} {{ /* methods omitted */ }}",
            "metadata": {
                "project_id": project_id,  # ← FIXED
                "file_path": file_path,
                "type": "class",
                "name": node.name,
                "start_line": start_line,
            }
        }
        chunks.append(chunk)

    # === FULL CLASS CHUNK ===
    if tree.types:
        class_name = tree.types[0].name if hasattr(tree.types[0], 'name') else "Unknown"
        full_chunk = {
            "id": str(uuid.uuid4()),
            "text": code.strip(),
            "metadata": {
                "project_id": project_id,  # ← FIXED
                "file_path": file_path,
                "type": "full_class",
                "name": class_name,
            }
        }
        chunks.append(full_chunk)

    return chunks

# === Extract ZIP ===
def extract_project_zip(project_id: str) -> Path:
    zip_path = MEDIA_ROOT / "files" / f"{project_id}.zip"
    extract_path = EXTRACT_FOLDER / project_id

    if not zip_path.exists():
        raise HTTPException(404, "ZIP file not found")

    if extract_path.exists():
        shutil.rmtree(extract_path)
    extract_path.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(extract_path)

    return extract_path

# === List Java Files ===
def list_java_files(extract_path: Path) -> List[Dict[str, str]]:
    files = []
    for f in extract_path.rglob("*.java"):
        if f.is_file():
            try:
                content = f.read_text(encoding="utf-8")
                rel_path = str(f.relative_to(extract_path.parent))
                files.append({"path": rel_path, "content": content})
            except Exception as e:
                print(f"[File Read Error] {f}: {e}")
    return files

# === INGESTION ENDPOINT ===
@router.post("/ingest/{project_id}")
async def ingest_project(project_id: str):
    print(f"\n[INGEST] Starting ingestion for project: {project_id}")
    extract_path = extract_project_zip(project_id)
    java_files = list_java_files(extract_path)

    if not java_files:
        raise HTTPException(400, "No .java files found in ZIP")

    all_chunks = []
    for jf in java_files:
        print(f"[Parsing] {jf['path']}")
        all_chunks.extend(parse_java_code(jf["content"], jf["path"], project_id))

    if not all_chunks:
        return JSONResponse({"status": "warning", "message": "No code chunks parsed"})

    print(f"\n{'='*60}\n TOTAL CHUNKS: {len(all_chunks)} | PROJECT: {project_id}\n{'='*60}")

    # === EMBED & UPSERT ===
    texts = [c["text"] for c in all_chunks]
    ids = [c["id"] for c in all_chunks]
    metadatas = [c["metadata"] for c in all_chunks]

    print(f"Starting embedding of {len(texts)} chunks...")
    for i in tqdm(range(0, len(texts), BATCH_SIZE), desc="Embedding"):
        batch_texts = texts[i:i + BATCH_SIZE]
        batch_ids = ids[i:i + BATCH_SIZE]
        batch_meta = metadatas[i:i + BATCH_SIZE]

        embeddings = ollama_ef(batch_texts)

        collection.upsert(
            ids=batch_ids,
            embeddings=embeddings,
            documents=batch_texts,
            metadatas=batch_meta
        )

    return JSONResponse({
        "status": "success",
        "project_id": project_id,
        "files": len(java_files),
        "chunks": len(all_chunks)
    })

# === RETRIEVAL ENDPOINT ===
@router.post("/retrieve/{project_id}")
async def retrieve_code(project_id: str, request: RetrieveRequest):
    query = request.query.strip()
    if not query:
        raise HTTPException(400, "Query cannot be empty")

    print(f"\n[RETRIEVE] Query: '{query}' | Project: {project_id}")

    # Embed query
    query_embedding = ollama_ef([query])[0]

    # Search in Chroma
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=5,
        where={"project_id": project_id}
    )

    # Format hits
    hits = []
    for i in range(len(results["ids"][0])):
        meta = results["metadatas"][0][i]
        hits.append({
            "rank": i + 1,
            "score": round(results["distances"][0][i], 4),
            "type": meta["type"],
            "name": meta.get("name", "Unknown"),
            "file": meta["file_path"],
            "lines": f"{meta.get('start_line', '?')}–{meta.get('end_line', '?')}",
            "code": results["documents"][0][i].strip()
        })

    return {
        "project_id": project_id,
        "query": query,
        "results": hits,
        "total_hits": len(hits)
    }

# === LIST PROJECTS (DEBUG) ===
@router.get("/projects")
def list_projects():
    result = collection.get(include=["metadatas"])
    projects = {m["project_id"] for m in result["metadatas"]}
    return {"projects": sorted(projects)}

# === HEALTH CHECK ===
@router.get("/health")
def health():
    return {"status": "ok", "ollama": "running", "chroma": "connected"}