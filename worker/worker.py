from __future__ import annotations

from redis import Redis
from rq import Connection, Queue, Worker

from gateway.app.config import get_gateway_config


def main() -> None:
    cfg = get_gateway_config()
    redis_conn = Redis.from_url(cfg.redis_url)
    with Connection(redis_conn):
        worker = Worker([Queue("admin"), Queue("default")], name="llm-switchboard-worker")
        worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
