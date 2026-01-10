import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings

from infrastructure.database import engine, Base
import infrastructure.models 

from api.routes import fishing, admin


Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Fisher Bot Game Engine",
    description="Microservice for fishing mechanics, RNG, and RPG progression.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(fishing.router, prefix="/v1", tags=["Fishing"])
app.include_router(admin.router, prefix="/v1/admin", tags=["Admin Panel"])


@app.get("/health")
def health_check():
    return {
        "status": "healthy", 
        "service": "game_engine",
        "database": "connected" 
    }

if __name__ == "__main__":
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=8000, 
        reload=True 
    )