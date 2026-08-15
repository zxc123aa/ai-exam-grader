"""Export wrongbook crops as PNG so they can be eyeballed outside the app."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
from sqlmodel import Session, select

from app.core.db import engine
from app.models import WrongQuestionEntry, WrongQuestionSource
from app.services.object_storage import materialize_storage_key

EXAM_ID = "d4989b5c-5d16-49c6-94c9-0e47c2c305be"
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "tmp-crops"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with Session(engine) as session:
        source_ids = [
            row.id
            for row in session.exec(
                select(WrongQuestionSource).where(
                    WrongQuestionSource.exam_id == EXAM_ID
                )
            ).all()
        ]
        entries = session.exec(
            select(WrongQuestionEntry).where(
                WrongQuestionEntry.source_id.in_(source_ids)
            )
        ).all()
    exported = 0
    for entry in entries:
        if not entry.image_storage_key:
            continue
        source = materialize_storage_key(entry.image_storage_key)
        with Image.open(source) as image:
            target = OUT_DIR / f"q{entry.question_label}.png"
            image.convert("RGB").save(target)
            print(f"q{entry.question_label} {image.size[0]}x{image.size[1]} -> {target}")
        exported += 1
    print(f"EXPORTED {exported}")
    return 0 if exported else 1


if __name__ == "__main__":
    sys.exit(main())
