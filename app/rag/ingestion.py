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

# === CONFIG ===
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MEDIA_ROOT = PROJECT_ROOT / "uploads"
EXTRACT_FOLDER = PROJECT_ROOT / "temp_extracted"
CHROMA_PATH = PROJECT_ROOT / "chroma_db"
OLLAMA_URL = "http://localhost:11434"
MODEL_NAME = "nomic-embed-text:latest"
BATCH_SIZE = 8

MEDIA_ROOT.mkdir(exist_ok=True)
EXTRACT_FOLDER.mkdir(exist_ok=True)
CHROMA_PATH.mkdir(exist_ok=True)

# === ChromaDB ===
client = chromadb.PersistentClient(path=str(CHROMA_PATH))
collection = client.get_or_create_collection(name="java_code")

# === Ollama Embedding Function ===
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
                return [0.0] * 768

    async def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        results = await asyncio.gather(*[self._embed_single(t) for t in texts], return_exceptions=True)
        return [[0.0] * 768 if isinstance(r, Exception) else r for r in results]

    def __call__(self, input: List[str]) -> List[List[float]]:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, self._embed_batch(input))
            return future.result()

ollama_ef = OllamaEmbeddingFunction(MODEL_NAME)

# === Parse Java Code ===
def parse_java_code(code: str, file_path: str, project_id: str) -> List[Dict[str, Any]]:
    chunks = []
    try:
        tree = javalang.parse.parse(code)
    except Exception as e:
        print(f"[Parse Error] {file_path}: {e}")
        return chunks

    lines = code.splitlines()

    # Method chunks
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
                "project_id": project_id,
                "file_path": file_path,
                "type": "method",
                "name": node.name,
                "start_line": start_line,
                "end_line": end_line,
            }
        }
        chunks.append(chunk)

    # Class chunks
    for _, node in tree.filter(javalang.tree.ClassDeclaration):
        start_line = node.position.line if node.position else 0
        chunk = {
            "id": str(uuid.uuid4()),
            "text": f"class {node.name} {{ /* methods omitted */ }}",
            "metadata": {
                "project_id": project_id,
                "file_path": file_path,
                "type": "class",
                "name": node.name,
                "start_line": start_line,
            }
        }
        chunks.append(chunk)

    # Full class chunk
    if tree.types:
        class_name = tree.types[0].name if hasattr(tree.types[0], 'name') else "Unknown"
        full_chunk = {
            "id": str(uuid.uuid4()),
            "text": code.strip(),
            "metadata": {
                "project_id": project_id,
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
        raise FileNotFoundError(f"ZIP not found: {zip_path}")

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

# === BACKGROUND INGESTION FUNCTION ===
async def ingest_project(project_id: str):
    print(f"[INGEST] Starting for project: {project_id}")
    try:
        extract_path = extract_project_zip(project_id)
        print(f"[INGEST] Extracted to: {extract_path}")
    except Exception as e:
        print(f"[INGEST] ZIP extraction failed: {e}")
        raise

    try:
        java_files = list_java_files(extract_path)
        print(f"[INGEST] Found {len(java_files)} Java files")
    except Exception as e:
        print(f"[INGEST] File listing failed: {e}")
        raise

    if not java_files:
        print("[INGEST] No .java files found")
        return

    all_chunks = []
    for jf in java_files:
        print(f"[INGEST] Parsing: {jf['path']}")
        try:
            chunks = parse_java_code(jf["content"], jf["path"], project_id)
            all_chunks.extend(chunks)
            print(f"  → {len(chunks)} chunks")
        except Exception as e:
            print(f"[INGEST] Parse failed for {jf['path']}: {e}")

    if not all_chunks:
        print("[INGEST] No chunks parsed")
        return

    print(f"[INGEST] Total chunks: {len(all_chunks)}")

    texts = [c["text"] for c in all_chunks]
    ids = [c["id"] for c in all_chunks]
    metadatas = [c["metadata"] for c in all_chunks]

    print("Embedding chunks...")
    for i in tqdm(range(0, len(texts), BATCH_SIZE), desc="Embedding"):
        batch_texts = texts[i:i + BATCH_SIZE]
        batch_ids = ids[i:i + BATCH_SIZE]
        batch_meta = metadatas[i:i + BATCH_SIZE]

        try:
            embeddings = ollama_ef(batch_texts)
            print(f"  → Batch {i//BATCH_SIZE + 1}: {len(embeddings)} embeddings")
            collection.upsert(
                ids=batch_ids,
                embeddings=embeddings,
                documents=batch_texts,
                metadatas=batch_meta
            )
        except Exception as e:
            print(f"[INGEST] Embedding/Upsert failed for batch {i}: {e}")
            raise

    print(f"[INGEST] Completed for {project_id}")