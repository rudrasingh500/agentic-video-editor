import os
from redis import Redis
from rq import Queue

REDIS_AUTH_URL = os.getenv("REDIS_AUTH_URL", "redis://localhost:6379/0")
REDIS_RQ_URL = os.getenv("REDIS_RQ_URL", "redis://localhost:6379/1")

redis_auth = Redis.from_url(REDIS_AUTH_URL, decode_responses=True)
redis_rq = Redis.from_url(REDIS_RQ_URL, decode_responses=True)

rq_queue = Queue("agent", connection=redis_rq)


def init_redis() -> None:
    redis_auth.ping()
    redis_rq.ping()
