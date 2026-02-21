import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from services.eventing.event_job_runner import FishingEventJobRunner
from services.eventing.se_job_runner import SEJobRunner

from infrastructure.database import engine, Base
import infrastructure.models 

from api.routes import fishing, admin, inventory, auth


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

app.include_router(auth.router, prefix="/v1/auth", tags=["Auth"])
app.include_router(fishing.router, prefix="/v1", tags=["Fishing"])
app.include_router(admin.router, prefix="/v1/admin", tags=["Admin Panel"])
app.include_router(inventory.router, prefix="/v1/inventory", tags=["Inventory"])

event_job_runner = FishingEventJobRunner(poll_interval_seconds=1.0, batch_size=50)
se_job_runner = SEJobRunner()


@app.on_event("startup")
async def start_background_workers():
    await event_job_runner.start()
    await se_job_runner.start()


@app.on_event("shutdown")
async def stop_background_workers():
    await event_job_runner.stop()
    await se_job_runner.stop()


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
