from rq import Worker, Queue

from redis_client import init_redis, redis_rq


def main():
    init_redis()
    worker = Worker([Queue("agent", connection=redis_rq)], connection=redis_rq)
    worker.work()


if __name__ == "__main__":
    main()
