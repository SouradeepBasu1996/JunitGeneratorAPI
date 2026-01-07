# app/controller/download_controller.py
import os
import io
import zipfile
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from app.config.settings import settings

from app.model.db import get_postgres  # asyncpg connection provider

router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXTRACT_FOLDER = PROJECT_ROOT / settings.EXTRACT_FOLDER


async def zip_directory(source_dir: Path, output_name: str) -> io.BytesIO:
    """
    Recursively zips all files and folders inside the extracted project directory.
    """
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer,
                         mode="w",
                         compression=zipfile.ZIP_DEFLATED) as zipf:

        for file_path in source_dir.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(source_dir)
                zipf.write(str(file_path), str(arcname))

    zip_buffer.seek(0)
    return zip_buffer


@router.post("/download/")
async def download_project(id: str = Query(..., alias="project_id")):

    # ---------- DB CONNECTION ----------
    db = await get_postgres()

    # ---------- VALIDATE ID EXISTS ----------
    id_check = await db.fetchval(
        "SELECT COUNT(*) FROM public.unittest WHERE id = $1;",
        id
    )

    if id_check == 0:
        raise HTTPException(
            status_code=404,
            detail="Invalid project_id: No matching record found in database"
        )

    # ---------- CHECK STATUS COMPLETED ----------
    file_data = await db.fetchrow(
        "SELECT uploaded_file_name, status "
        "FROM public.unittest WHERE id = $1;",
        id
    )

    if not file_data:
        raise HTTPException(
            status_code=404,
            detail="Project metadata not found."
        )

    status = file_data["status"]
    uploaded_file_name = file_data["uploaded_file_name"]

    if status.lower() != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Project status is not completed. Current status: {status}"
        )

    # ---------- LOCATE EXTRACTED PROJECT ----------
    project_dir = EXTRACT_FOLDER / id

    if not project_dir.exists():
        raise HTTPException(
            status_code=404,
            detail="Extracted project folder not found in EXTRACT_FOLDER"
        )

    # ---------- ZIP PROJECT ----------
    zip_buffer = await zip_directory(project_dir, uploaded_file_name)
    print("uploaded file name : ",uploaded_file_name)
    zip_name = f"{uploaded_file_name}"

    # ---------- RETURN STREAM ----------
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename={zip_name}"
        }
    )
