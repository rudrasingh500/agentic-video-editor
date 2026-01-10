from rq import Worker, Connection, Queue
from __init__ import init_redis, redis_rq

def main():
    init_redis()
    with Connection(redis_rq):
        worker = Worker([Queue("agent")])
        worker.work()

if __name__ == "__main__":
    main()
