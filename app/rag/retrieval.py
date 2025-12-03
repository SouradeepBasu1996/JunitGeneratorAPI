# app/rag/retrieval.py
import asyncio
from typing import List, Dict

from app.rag.ingestion import ollama_ef, collection


async def retrieve_context(project_id: str, query: str, n_results: int = 10) -> str:
    """
    Retrieve relevant code chunks for a query.
    Returns concatenated code with comments.
    """
    print(f"\n[BACKGROUND RETRIEVE] Query: '{query}' | Project: {project_id}")

    # embeddings call is sync, so push to a thread to avoid blocking the event loop
    query_embedding_list = await asyncio.to_thread(ollama_ef, [query])
    query_embedding = query_embedding_list[0]

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where={"project_id": project_id}
    )

    if not results.get("ids") or not results["ids"][0]:
        print("[RETRIEVE] No results from Chroma")
        return ""

    context_parts: List[str] = []
    for i in range(len(results["ids"][0])):
        meta: Dict = results["metadatas"][0][i]
        code: str = results["documents"][0][i].strip()
        name = meta.get("name", "Unknown")
        file_path = meta.get("file_path", "?")
        lines = f"{meta.get('start_line', '?')}–{meta.get('end_line', '?')}"

        header = f"// [{i + 1}] {name} | {file_path}:{lines}"
        context_parts.append(f"{header}\n{code}\n")

    return "\n".join(context_parts)
