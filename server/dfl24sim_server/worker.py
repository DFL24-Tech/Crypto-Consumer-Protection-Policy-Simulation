"""Worker entrypoint: applies schema idempotently, then consumes jobs until stopped."""
import asyncio

from . import db
from .jobs import app


async def _run() -> None:
    async with app.open_async():
        await app.run_worker_async()


def main() -> None:
    db.apply_schema(db.get_dsn())
    asyncio.run(_run())


if __name__ == "__main__":
    main()
