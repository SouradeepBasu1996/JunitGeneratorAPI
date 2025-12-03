from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    EMBEDDING_MODEL: str
    EMBEDDING_DIM: int
    EMBED_BATCH_SIZE: int
    LLM_URL: str
    CHROMA_COLLECTION: str

    MEDIA_ROOT: str
    EXTRACT_FOLDER: str
    CHROMA_PATH: str

    EMBED_TIMEOUT: int

    AUTO_CREATE_DIRECTORIES: bool = True
    AUTO_CREATE_PARENT_DIRECTORIES: bool = True

    DATABASE_URL: str | None = None
    UPLOAD_DIRECTORY: str | None = None
    GENERATED_TEST_DIRECTORY: str | None = None
    CONNECTION_STRING: str | None = None

    class Config:
        env_file = ".env"

settings = Settings()