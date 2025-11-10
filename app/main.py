from fastapi import FastAPI # type: ignore
from app.controller.upload_controller import router as upload_router
from app.controller.generate_test_controller import router as generate_router
from app.controller.generateTest_controller import router as generate_test_router
from app.controller.rag_ingestion_controller import router as ingestion_router
#from app.controller.download_controller import router as download_router
#from app.controller.coverage_controller import router as coverage_router
#from app.controller.list_unittest_controller import router as list_unittests_router

from app.model.db import init_postgres, close_postgres
#from app.middleware.cors_middleware import setup_cors

app = FastAPI()

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
app.include_router(generate_router)
app.include_router(generate_test_router)
app.include_router(ingestion_router)
#app.include_router(download_router)
#app.include_router(coverage_router)
#app.include_router(list_unittests_router)