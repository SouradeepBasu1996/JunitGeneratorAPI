# app/rag/retrieval.py
from app.rag.ingestion import ollama_ef, collection
from typing import List, Dict

async def retrieve_context(project_id: str, query: str, n_results: int = 10) -> str:
    """
    Retrieve relevant code chunks for a query.
    Returns concatenated code with comments.
    """
    print(f"\n[BACKGROUND RETRIEVE] Query: '{query}' | Project: {project_id}")

    query_embedding = ollama_ef([query])[0]

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where={"project_id": project_id}
    )

    context = ""
    for i in range(len(results["ids"][0])):
        meta = results["metadatas"][0][i]
        code = results["documents"][0][i].strip()
        name = meta.get("name", "Unknown")
        file_path = meta["file_path"]
        lines = f"{meta.get('start_line', '?')}–{meta.get('end_line', '?')}"

        context += f"// [{i+1}] {name} | {file_path}:{lines}\n{code}\n\n"

    return context