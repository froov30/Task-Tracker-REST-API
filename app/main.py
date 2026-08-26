from fastapi import FastAPI

from app.database import init_db
from app.routers.tasks import router as tasks_router

app = FastAPI(title="Task Tracker REST API")
app.include_router(tasks_router, prefix="/tasks")


@app.on_event("startup")
def on_startup() -> None:
    init_db()
