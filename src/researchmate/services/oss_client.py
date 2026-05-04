from __future__ import annotations

import hashlib
import importlib
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import quote

from researchmate.config import Settings, get_settings
from researchmate.services.documents import infer_paper_id

_T = TypeVar("_T")
_MULTIPART_THRESHOLD_BYTES = 10 * 1024 * 1024


class OssClientError(RuntimeError):
    """Raised when an OSS operation fails after retries."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_key_part(value: str) -> str:
    path = Path(value)
    cleaned = infer_paper_id(path)
    suffix = path.suffix.lower()
    if suffix and cleaned.endswith(suffix):
        return cleaned or "object"
    return f"{cleaned}{suffix}" if suffix else (cleaned or "object")


class OssClient:
    """Aliyun OSS wrapper with a local object-store fallback for development.

    When OSS credentials are incomplete the client stores objects under
    ``settings.oss_local_dir`` using the same key-oriented API. That keeps
    M3's CLI and smoke tests fully runnable without cloud credentials.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.local_dir = self.settings.oss_local_dir
        self.local_dir.mkdir(parents=True, exist_ok=True)
        self._bucket: Any | None = None

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> OssClient:
        return cls(settings=settings)

    @property
    def is_remote(self) -> bool:
        return self.settings.has_oss_credentials

    def put_file(self, local_path: str | Path, key: str | None = None) -> str:
        source = Path(local_path)
        if not source.exists():
            msg = f"file not found: {source}"
            raise FileNotFoundError(msg)
        object_key = key or self.default_key_for_file(source)
        if self.is_remote:
            self._retry(lambda: self._put_remote(source, object_key))
        else:
            destination = self._local_path(object_key)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        return object_key

    def get_file(self, key: str, destination: str | Path) -> Path:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        if self.is_remote:
            self._retry(lambda: self._get_remote(key, target))
        else:
            source = self._local_path(key)
            if not source.exists():
                msg = f"object not found in local OSS store: {key}"
                raise FileNotFoundError(msg)
            shutil.copyfile(source, target)
        return target

    def exists(self, key: str) -> bool:
        if self.is_remote:
            try:
                return bool(self._retry(lambda: self._remote_exists(key)))
            except OssClientError:
                return False
        return self._local_path(key).exists()

    def sign_url(self, key: str, expires: int = 3600) -> str:
        if self.is_remote:
            return str(self._retry(lambda: self._remote_sign_url(key, expires)))
        return f"file://{self._local_path(key).resolve()}"

    def default_key_for_file(self, path: str | Path, *, prefix: str = "uploads") -> str:
        file_path = Path(path)
        digest = sha256_file(file_path)[:16]
        return f"{prefix}/{digest}/{_safe_key_part(file_path.name)}"

    def _local_path(self, key: str) -> Path:
        clean_parts = [part for part in Path(key).parts if part not in {"", ".", ".."}]
        if not clean_parts:
            msg = "OSS key must not be empty"
            raise ValueError(msg)
        return self.local_dir.joinpath(*clean_parts)

    def _retry(self, operation: Callable[[], _T]) -> _T:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return operation()
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.25 * (2**attempt))
        msg = f"OSS operation failed after retries: {last_error}"
        raise OssClientError(msg) from last_error

    def _get_bucket(self) -> Any:
        if self._bucket is None:
            oss2 = importlib.import_module("oss2")
            secret = self.settings.oss_access_key_secret
            if (
                not self.settings.oss_access_key_id
                or secret is None
                or not self.settings.oss_endpoint
                or not self.settings.oss_bucket
            ):
                msg = "OSS credentials are incomplete"
                raise OssClientError(msg)
            auth = oss2.Auth(
                self.settings.oss_access_key_id,
                secret.get_secret_value(),
            )
            self._bucket = oss2.Bucket(
                auth,
                self.settings.oss_endpoint,
                self.settings.oss_bucket,
            )
        return self._bucket

    def _put_remote(self, source: Path, key: str) -> None:
        oss2 = importlib.import_module("oss2")
        bucket = self._get_bucket()
        if source.stat().st_size > _MULTIPART_THRESHOLD_BYTES:
            oss2.resumable_upload(
                bucket,
                key,
                str(source),
                multipart_threshold=_MULTIPART_THRESHOLD_BYTES,
            )
        else:
            bucket.put_object_from_file(key, str(source))

    def _get_remote(self, key: str, destination: Path) -> None:
        bucket = self._get_bucket()
        bucket.get_object_to_file(key, str(destination))

    def _remote_exists(self, key: str) -> bool:
        bucket = self._get_bucket()
        return bool(bucket.object_exists(key))

    def _remote_sign_url(self, key: str, expires: int) -> str:
        bucket = self._get_bucket()
        return str(bucket.sign_url("GET", quote(key, safe="/"), expires))
