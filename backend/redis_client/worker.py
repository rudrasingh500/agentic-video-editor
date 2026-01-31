import os

from rq import Queue, Worker
from rq.job import Job
from rq.worker import SimpleWorker

from redis_client import init_redis, redis_rq


class LoggingWorker(Worker):
    def handle_exception(self, job: Job, *exc_info) -> None:
        self.log.error("Job failed: %s", job.id, exc_info=exc_info)
        super().handle_exception(job, *exc_info)


class LoggingSimpleWorker(SimpleWorker):
    def handle_exception(self, job: Job, *exc_info) -> None:
        self.log.error("Job failed: %s", job.id, exc_info=exc_info)
        super().handle_exception(job, *exc_info)


def main():
    init_redis()
    if os.name == "nt":
        worker = LoggingSimpleWorker(
            [Queue("agent", connection=redis_rq)], connection=redis_rq
        )
    else:
        worker = LoggingWorker([Queue("agent", connection=redis_rq)], connection=redis_rq)
    worker.work()


if __name__ == "__main__":
    main()
