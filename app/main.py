from fastapi import FastAPI # type: ignore
from app.controller.upload_controller import router as upload_router
from app.controller.generateTest_controller import router as generate_test_router

from app.model.db import init_postgres, close_postgres
#from app.middleware.cors_middleware import setup_cors

app = FastAPI(
    title="JUnit Gen API",
    description="Generates JUnit testcases for Java projects. Uses llama3 from Ollama and RAG to ",
    version="1.0.0"
)

# Enable CORS
#setup_cors(app)

# Initialize PostgreSQL connection pool on startup
@app.on_event("startup")
async def startup():
    await init_postgres()

# Close PostgreSQL connection pool on shutdown
@app.on_event("shutdown")
async def shutdown():
    await close_postgres()

# Include routers
app.include_router(upload_router)

app.include_router(generate_test_router)
