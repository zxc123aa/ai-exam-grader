from __future__ import annotations

import argparse
import logging
from pathlib import Path

from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models import StoredFile
from app.services.object_storage import OssStorageBackend

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="将点凡阅卷本地文件幂等迁移到阿里云 OSS"
    )
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if settings.STORAGE_BACKEND != "oss":
        raise SystemExit("Set STORAGE_BACKEND=oss before running this migration")

    source_dir = args.source_dir.resolve()
    backend = OssStorageBackend()
    migrated = 0
    missing = 0
    with Session(engine) as session:
        stored_files = session.exec(
            select(StoredFile).order_by(StoredFile.created_at)
        ).all()
        if args.limit > 0:
            stored_files = stored_files[: args.limit]
        for stored_file in stored_files:
            source = (source_dir / stored_file.storage_key).resolve()
            if not source.is_relative_to(source_dir) or not source.is_file():
                missing += 1
                continue
            if not args.dry_run:
                backend.put_file(stored_file.storage_key, source)
            migrated += 1

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logger.info("migrated=%s missing=%s dry_run=%s", migrated, missing, args.dry_run)


if __name__ == "__main__":
    main()
