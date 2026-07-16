"""One-shot schema migration entrypoint (runs as the compose init service)."""
from . import db


def main() -> None:
    dsn = db.get_dsn()
    db.apply_schema(dsn)
    print("schema applied")


if __name__ == "__main__":
    main()
