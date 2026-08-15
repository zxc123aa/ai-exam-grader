"""Read-only check: which pages the wrongbook crops came from.

`page_renders` in the snapshot log is the number of distinct (file, page) pairs the
crop step had to rasterize, so counting those pairs here reproduces it without
re-running a release.
"""

from __future__ import annotations

import sys

from sqlmodel import Session, select

from app.core.db import engine
from app.models import (
    StudentSubmission,
    SubmissionAnnotation,
    WrongQuestionEntry,
    WrongQuestionSource,
)
from app.services.object_storage import materialize_storage_key

EXAM_ID = "d4989b5c-5d16-49c6-94c9-0e47c2c305be"


def main() -> int:
    with Session(engine) as session:
        source_ids = [
            row.id
            for row in session.exec(
                select(WrongQuestionSource).where(
                    WrongQuestionSource.exam_id == EXAM_ID
                )
            ).all()
        ]
        if not source_ids:
            print("no wrongbook sources for this exam")
            return 1
        entries = session.exec(
            select(WrongQuestionEntry).where(
                WrongQuestionEntry.source_id.in_(source_ids)
            )
        ).all()
        pairs: set[tuple[str, int]] = set()
        wrong = 0
        for entry in entries:
            if not entry.is_wrong:
                continue
            wrong += 1
            annotation = session.get(SubmissionAnnotation, entry.annotation_id)
            submission = session.get(StudentSubmission, entry.submission_id)
            if not annotation or not submission:
                print(f"{entry.question_label}: missing annotation/submission")
                continue
            pairs.add((str(submission.stored_file_id), annotation.page_number))
            crop = (
                materialize_storage_key(entry.image_storage_key)
                if entry.image_storage_key
                else None
            )
            print(
                f"wrong {entry.question_label} page={annotation.page_number} "
                f"bbox=({annotation.x:.3f},{annotation.y:.3f}) "
                f"{annotation.width:.3f}x{annotation.height:.3f}"
            )
            if crop:
                print(f"  crop={crop}")
            for point in entry.missed_points:
                print(f"  missed: {point}")
            if entry.student_answer_text:
                print(f"  student_answer: {entry.student_answer_text[:160]}")
        print(f"wrong_entries={wrong} distinct_page_renders={len(pairs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
