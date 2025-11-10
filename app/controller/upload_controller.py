import shutil
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, Query, HTTPException # type: ignore
from app.model.db import get_postgres
import asyncpg # type: ignore
import os

router = APIRouter()
MEDIA_ROOT = "uploads"

async def save_uploaded_file(inputfile: UploadFile, file_uuid: str):
    """Saves the uploaded file using the same UUID as the database."""
    save_path = Path(MEDIA_ROOT) / 'files'
    save_path.mkdir(parents=True, exist_ok=True)

    file_ext = Path(inputfile.filename).suffix.lower()
    file_name = f"{file_uuid}{file_ext}"  # Use DB UUID for filename
    file_path = save_path / file_name

    with open(file_path, 'wb') as dest:
        shutil.copyfileobj(inputfile.file, dest)

    #If the file is NOT already a .zip, compress it

    return (file_path), file_name


@router.post("/upload/")
async def upload_file(
    file: UploadFile = File(...),
    project_type: str = Form(...),
    unit_test_type: str = Form(...),
    username: str = Query(...)
):
    """Handles file upload and ensures stored filename matches DB UUID."""
    try:
        db: asyncpg.Pool = await get_postgres()
        async with db.acquire() as conn:
            result = await conn.fetchval(
                """
                INSERT INTO public.unittest 
                (id, uploaded_file_name, project_type, unit_test_type, output_project_name, uploaded_date, processed_date, username, status)
                VALUES (uuid_generate_v4(), $1, $2, $3, '', NOW(), NOW(), $4, 'created')
                RETURNING id;
                """,
                file.filename, project_type, unit_test_type,username
            )

            if result:
                file_uuid = str(result)  # Use the generated UUID from DB
                file_path, file_name = await save_uploaded_file(file, file_uuid)
                print(file_path)
                absolute_path=str(file_path.resolve())
                print(absolute_path)

                await conn.execute(
                    "UPDATE public.unittest SET output_project_name = $1 WHERE id = $2;",
                    file_name, result
                )

                return {
                    "statusMessage": "success",
                    "status": "created",
                    "id": result,
                    "file_path": absolute_path,
                    "file_name": file_name
                }

        raise ValueError("Database insertion failed")

    except Exception as e:
        print(f"Error during upload: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")