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
from handlers.generation_handler import router as generation_router
from handlers.health_handler import router as health_router
from handlers.project_handler import router as project_router
from handlers.render_handler import router as render_router
from handlers.snippet_handler import router as snippet_router
from handlers.timeline_handler import router as timeline_router

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


def _attach_file_handler(
    logger_name: str,
    log_file_path: Path,
    level_name: str | None = None,
) -> None:
    logger_level = (level_name or LOG_LEVEL).upper()
    logger_level_value = getattr(logging, logger_level, logging.INFO)

    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setLevel(logger_level_value)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )

    target_logger = logging.getLogger(logger_name)
    if not any(
        isinstance(handler, logging.FileHandler)
        and getattr(handler, "baseFilename", None) == str(log_file_path)
        for handler in target_logger.handlers
    ):
        target_logger.addHandler(file_handler)
    target_logger.setLevel(logger_level_value)

EDIT_AGENT_LOG_FILE = os.getenv("EDIT_AGENT_LOG_FILE", "").strip()
if EDIT_AGENT_LOG_FILE:
    log_path = Path(EDIT_AGENT_LOG_FILE)
    if not log_path.is_absolute():
        log_path = ROOT_DIR / log_path
    _attach_file_handler("agent.edit_agent", log_path)

ASSET_PROCESSING_LOG_FILE = os.getenv(
    "ASSET_PROCESSING_LOG_FILE", "backend/log/asset_processing.log"
).strip()
ASSET_PROCESSING_LOG_LEVEL = os.getenv("ASSET_PROCESSING_LOG_LEVEL", "INFO").strip()
if ASSET_PROCESSING_LOG_FILE:
    asset_log_path = Path(ASSET_PROCESSING_LOG_FILE)
    if not asset_log_path.is_absolute():
        asset_log_path = ROOT_DIR / asset_log_path
    _attach_file_handler("agent.asset_processing", asset_log_path, level_name=ASSET_PROCESSING_LOG_LEVEL)

AGENT_RUNS_AND_JOBS_LOG_FILE = os.getenv(
    "AGENT_RUNS_AND_JOBS_LOG_FILE", "backend/log/agent_runs_and_jobs.log"
).strip()
AGENT_RUNS_AND_JOBS_LOG_LEVEL = os.getenv("AGENT_RUNS_AND_JOBS_LOG_LEVEL", "INFO").strip()
if AGENT_RUNS_AND_JOBS_LOG_FILE:
    agent_job_log_path = Path(AGENT_RUNS_AND_JOBS_LOG_FILE)
    if not agent_job_log_path.is_absolute():
        agent_job_log_path = ROOT_DIR / agent_job_log_path
    _attach_file_handler("agent.edit_agent", agent_job_log_path, level_name=AGENT_RUNS_AND_JOBS_LOG_LEVEL)
    _attach_file_handler("handlers.edit_handler", agent_job_log_path, level_name=AGENT_RUNS_AND_JOBS_LOG_LEVEL)
    _attach_file_handler("handlers.render_handler", agent_job_log_path, level_name=AGENT_RUNS_AND_JOBS_LOG_LEVEL)
    _attach_file_handler("operators.render_operator", agent_job_log_path, level_name=AGENT_RUNS_AND_JOBS_LOG_LEVEL)
    _attach_file_handler("utils.cloud_run_jobs", agent_job_log_path, level_name=AGENT_RUNS_AND_JOBS_LOG_LEVEL)

app = FastAPI(app_name="Agent Editor Backend")


app.include_router(health_router)
app.include_router(auth_router)
app.include_router(project_router)
app.include_router(asset_router)
app.include_router(generation_router)
app.include_router(snippet_router)
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
