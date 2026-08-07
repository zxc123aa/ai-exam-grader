from types import SimpleNamespace

from app.models import GradingItemStatus
from app.services.grading_workflow import _review_item_count


def test_review_item_count_counts_questions_instead_of_students() -> None:
    items = [
        SimpleNamespace(status=GradingItemStatus.NEEDS_REVIEW),
        SimpleNamespace(status=GradingItemStatus.NEEDS_REVIEW),
        SimpleNamespace(status=GradingItemStatus.FAILED),
        SimpleNamespace(status=GradingItemStatus.COMPLETED),
    ]

    assert _review_item_count(items) == 3
