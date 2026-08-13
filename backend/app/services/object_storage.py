from __future__ import annotations

import shutil
import uuid
from pathlib import Path, PurePosixPath
from typing import Protocol

import oss2

from app.core.config import settings


class ObjectStorageError(RuntimeError):
    pass


class StorageBackend(Protocol):
    def materialize(self, storage_key: str) -> Path: ...

    def put_file(self, storage_key: str, source: Path) -> Path: ...

    def put_bytes(self, storage_key: str, contents: bytes) -> Path: ...

    def delete(self, storage_key: str) -> None: ...


def normalize_storage_key(storage_key: str) -> str:
    key = PurePosixPath(storage_key.replace("\\", "/"))
    if (
        key.is_absolute()
        or not key.parts
        or any(part in {"", ".", ".."} for part in key.parts)
    ):
        raise ObjectStorageError("Invalid storage key")
    return key.as_posix()


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copyfile(source, temp_path)
        temp_path.replace(target)
    finally:
        temp_path.unlink(missing_ok=True)


def _atomic_write(target: Path, contents: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_bytes(contents)
        temp_path.replace(target)
    finally:
        temp_path.unlink(missing_ok=True)


class LocalStorageBackend:
    def _path(self, storage_key: str) -> Path:
        return settings.LOCAL_UPLOAD_DIR / normalize_storage_key(storage_key)

    def materialize(self, storage_key: str) -> Path:
        return self._path(storage_key)

    def put_file(self, storage_key: str, source: Path) -> Path:
        target = self._path(storage_key)
        if source.resolve() != target.resolve():
            _atomic_copy(source, target)
        return target

    def put_bytes(self, storage_key: str, contents: bytes) -> Path:
        target = self._path(storage_key)
        _atomic_write(target, contents)
        return target

    def delete(self, storage_key: str) -> None:
        _remove_local_path(self._path(storage_key))


class OssStorageBackend:
    def __init__(self) -> None:
        auth = oss2.Auth(settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)
        self.bucket = oss2.Bucket(auth, settings.OSS_ENDPOINT, settings.OSS_BUCKET_NAME)

    def _object_key(self, storage_key: str) -> str:
        key = normalize_storage_key(storage_key)
        prefix = settings.OSS_PREFIX.strip("/")
        return f"{prefix}/{key}" if prefix else key

    def _cache_path(self, storage_key: str) -> Path:
        return settings.STORAGE_CACHE_DIR / normalize_storage_key(storage_key)

    def materialize(self, storage_key: str) -> Path:
        target = self._cache_path(storage_key)
        if target.exists():
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            self.bucket.get_object_to_file(
                self._object_key(storage_key), str(temp_path)
            )
            temp_path.replace(target)
        except oss2.exceptions.OssError as exc:
            raise ObjectStorageError("Unable to read object from OSS") from exc
        finally:
            temp_path.unlink(missing_ok=True)
        return target

    def put_file(self, storage_key: str, source: Path) -> Path:
        try:
            self.bucket.put_object_from_file(self._object_key(storage_key), str(source))
        except oss2.exceptions.OssError as exc:
            raise ObjectStorageError("Unable to write object to OSS") from exc
        target = self._cache_path(storage_key)
        if source.resolve() != target.resolve():
            _atomic_copy(source, target)
        return target

    def put_bytes(self, storage_key: str, contents: bytes) -> Path:
        try:
            self.bucket.put_object(self._object_key(storage_key), contents)
        except oss2.exceptions.OssError as exc:
            raise ObjectStorageError("Unable to write object to OSS") from exc
        target = self._cache_path(storage_key)
        _atomic_write(target, contents)
        return target

    def delete(self, storage_key: str) -> None:
        try:
            self.bucket.delete_object(self._object_key(storage_key))
        except oss2.exceptions.OssError as exc:
            raise ObjectStorageError("Unable to delete object from OSS") from exc
        _remove_local_path(self._cache_path(storage_key))


def _remove_local_path(path: Path) -> None:
    path.unlink(missing_ok=True)
    current = path.parent
    roots = {settings.LOCAL_UPLOAD_DIR.resolve(), settings.STORAGE_CACHE_DIR.resolve()}
    while current.exists() and current.resolve() not in roots:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def get_storage_backend() -> StorageBackend:
    if settings.STORAGE_BACKEND == "oss":
        return OssStorageBackend()
    return LocalStorageBackend()


def check_storage_backend() -> None:
    if settings.STORAGE_BACKEND == "oss":
        try:
            OssStorageBackend().bucket.get_bucket_info()
        except oss2.exceptions.OssError as exc:
            raise ObjectStorageError("OSS is unavailable") from exc
        return
    settings.LOCAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if not settings.LOCAL_UPLOAD_DIR.is_dir():
        raise ObjectStorageError("Local upload directory is unavailable")
    probe = settings.LOCAL_UPLOAD_DIR / f".health-{uuid.uuid4().hex}"
    try:
        probe.write_bytes(b"")
    finally:
        probe.unlink(missing_ok=True)


def materialize_storage_key(storage_key: str) -> Path:
    return get_storage_backend().materialize(storage_key)


def put_storage_file(storage_key: str, source: Path) -> Path:
    return get_storage_backend().put_file(storage_key, source)


def put_storage_bytes(storage_key: str, contents: bytes) -> Path:
    return get_storage_backend().put_bytes(storage_key, contents)


def delete_storage_key(storage_key: str) -> None:
    get_storage_backend().delete(storage_key)


def storage_key_from_path(path: Path) -> str | None:
    resolved = path.resolve()
    root = (
        settings.STORAGE_CACHE_DIR.resolve()
        if settings.STORAGE_BACKEND == "oss"
        else settings.LOCAL_UPLOAD_DIR.resolve()
    )
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return None
