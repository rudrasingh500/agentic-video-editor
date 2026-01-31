import logging
import os
from pathlib import Path

from dotenv import load_dotenv

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from handlers.asset_handler import router as asset_router
from handlers.auth_handler import router as auth_router
from handlers.edit_handler import router as edit_router
from handlers.health_handler import router as health_router
from handlers.project_handler import router as project_router
from handlers.render_handler import router as render_router
from handlers.timeline_handler import router as timeline_router

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

app = FastAPI(app_name="Agent Editor Backend")


app.include_router(health_router)
app.include_router(auth_router)
app.include_router(project_router)
app.include_router(asset_router)
app.include_router(timeline_router)
app.include_router(render_router)
app.include_router(edit_router, prefix="/projects/{project_id}/edit", tags=["edit"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:4173",
        "http://localhost:5173",
        "http://localhost:5174",
    ],
    allow_origin_regex=r"^null$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
