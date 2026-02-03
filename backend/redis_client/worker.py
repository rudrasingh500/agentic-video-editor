import os

from rq import Queue, Worker
from rq.job import Job
from rq.worker import SimpleWorker, SpawnWorker

from redis_client import init_redis, redis_rq


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
    init_redis()
    worker = _build_worker()
    worker.work()


if __name__ == "__main__":
    main()
