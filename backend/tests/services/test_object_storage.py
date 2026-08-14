from pathlib import Path

import pytest

from app.core.config import settings
from app.services.object_storage import (
    LocalStorageBackend,
    ObjectStorageError,
    normalize_storage_key,
    storage_key_from_path,
)


def test_normalize_storage_key_rejects_path_traversal() -> None:
    for value in ("../secret", "/absolute/path", "owner/../../secret"):
        with pytest.raises(ObjectStorageError):
            normalize_storage_key(value)


def test_local_storage_round_trip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(settings, "LOCAL_UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(settings, "STORAGE_CACHE_DIR", tmp_path / "cache")

    backend = LocalStorageBackend()
    target = backend.put_bytes("owner/file.txt", b"dianfan")

    assert target.read_bytes() == b"dianfan"
    assert backend.materialize("owner/file.txt") == target
    assert storage_key_from_path(target) == "owner/file.txt"

    backend.delete("owner/file.txt")
    assert not target.exists()
