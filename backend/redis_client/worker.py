import os
import logging
import sys
from pathlib import Path

from rq import Queue, Worker
from rq.job import Job
from rq.worker import SimpleWorker, SpawnWorker

from redis_client import init_redis, redis_rq


logger = logging.getLogger(__name__)


ROOT_DIR = Path(__file__).resolve().parents[2]
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


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


def _configure_worker_logging() -> None:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    asset_log = os.getenv(
        "ASSET_PROCESSING_LOG_FILE", "backend/log/asset_processing.log"
    ).strip()
    asset_log_level = os.getenv("ASSET_PROCESSING_LOG_LEVEL", "INFO").strip()
    if asset_log:
        asset_log_path = Path(asset_log)
        if not asset_log_path.is_absolute():
            asset_log_path = ROOT_DIR / asset_log_path
        _attach_file_handler("agent.asset_processing", asset_log_path, level_name=asset_log_level)

    runs_jobs_log = os.getenv(
        "AGENT_RUNS_AND_JOBS_LOG_FILE", "backend/log/agent_runs_and_jobs.log"
    ).strip()
    runs_jobs_log_level = os.getenv("AGENT_RUNS_AND_JOBS_LOG_LEVEL", "INFO").strip()
    if runs_jobs_log:
        runs_jobs_path = Path(runs_jobs_log)
        if not runs_jobs_path.is_absolute():
            runs_jobs_path = ROOT_DIR / runs_jobs_path
        _attach_file_handler("redis_client.worker", runs_jobs_path, level_name=runs_jobs_log_level)
        _attach_file_handler("agent.edit_agent", runs_jobs_path, level_name=runs_jobs_log_level)
        _attach_file_handler("operators.render_operator", runs_jobs_path, level_name=runs_jobs_log_level)
        _attach_file_handler("utils.cloud_run_jobs", runs_jobs_path, level_name=runs_jobs_log_level)
        _attach_file_handler("rq.worker", runs_jobs_path, level_name=runs_jobs_log_level)


class LoggingWorker(Worker):
    def handle_exception(self, job: Job, *exc_info) -> None:
        self.log.error("Job failed: %s", job.id, exc_info=exc_info)
        super().handle_exception(job, *exc_info)


class LoggingSimpleWorker(SimpleWorker):
    def handle_exception(self, job: Job, *exc_info) -> None:
        self.log.error("Job failed: %s", job.id, exc_info=exc_info)
        super().handle_exception(job, *exc_info)


class LoggingSpawnWorker(SpawnWorker):
    def handle_exception(self, job: Job, *exc_info) -> None:
        self.log.error("Job failed: %s", job.id, exc_info=exc_info)
        super().handle_exception(job, *exc_info)


def _build_worker() -> Worker:
    queues = [Queue("agent", connection=redis_rq)]
    override = os.getenv("RQ_WORKER_CLASS", "").strip().lower()
    supports_wait4 = hasattr(os, "wait4")
    supports_fork = supports_wait4 and hasattr(os, "fork")
    supports_spawn = supports_wait4 and hasattr(os, "spawnv")
    if override == "simple":
        return LoggingSimpleWorker(queues, connection=redis_rq)
    if override == "spawn" and supports_spawn:
        return LoggingSpawnWorker(queues, connection=redis_rq)
    if override == "fork" and supports_fork:
        return LoggingWorker(queues, connection=redis_rq)
    if supports_fork:
        return LoggingWorker(queues, connection=redis_rq)
    if supports_spawn:
        return LoggingSpawnWorker(queues, connection=redis_rq)
    return LoggingSimpleWorker(queues, connection=redis_rq)


def main():
    _configure_worker_logging()
    logger.info("rq_worker_start python_executable=%s", sys.executable)
    try:
        import mediapipe as mp  # type: ignore[import-not-found]

        logger.info(
            "rq_worker_mediapipe_available version=%s has_solutions=%s",
            getattr(mp, "__version__", "unknown"),
            hasattr(mp, "solutions"),
        )
    except Exception as exc:  # pragma: no cover - runtime dependency diagnostics
        logger.warning("rq_worker_mediapipe_unavailable error=%s", f"{type(exc).__name__}: {exc}")

    init_redis()
    worker = _build_worker()
    worker.work()


if __name__ == "__main__":
    main()
