from __future__ import annotations

import argparse
import json
import tempfile
import zipfile
from pathlib import Path

from researchmate.config import get_settings
from researchmate.services.oss_client import OssClient


def _safe_archive_name() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _zip_data_directory(data_dir: Path, archive_path: Path) -> None:
    if not data_dir.exists():
        msg = f"data directory not found: {data_dir}"
        raise FileNotFoundError(msg)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for path in sorted(data_dir.rglob("*")):
            if path.is_file():
                zip_file.write(path, arcname=path.relative_to(data_dir))


def _backup(data_dir: Path, archive_key: str | None = None) -> dict[str, str]:
    settings = get_settings()
    oss_client = OssClient.from_settings(settings)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as temp_file:
        temp_path = Path(temp_file.name)
    try:
        _zip_data_directory(data_dir, temp_path)
        key = archive_key or f"backups/data/{_safe_archive_name()}.zip"
        uploaded_key = oss_client.put_file(temp_path, key=key)
        return {
            "archive_key": uploaded_key,
            "archive_url": oss_client.sign_url(uploaded_key),
            "data_dir": str(data_dir),
        }
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _restore(archive_key: str, target_dir: Path) -> dict[str, str]:
    settings = get_settings()
    oss_client = OssClient.from_settings(settings)
    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as temp_file:
        temp_path = Path(temp_file.name)
    try:
        oss_client.get_file(archive_key, temp_path)
        with zipfile.ZipFile(temp_path, "r") as zip_file:
            target_root = target_dir.resolve()
            for member in zip_file.infolist():
                destination = (target_dir / member.filename).resolve()
                if not str(destination).startswith(str(target_root)):
                    msg = f"unsafe archive member path: {member.filename}"
                    raise ValueError(msg)
            zip_file.extractall(target_dir)
        return {
            "archive_key": archive_key,
            "target_dir": str(target_dir),
            "archive_url": oss_client.sign_url(archive_key),
        }
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backup or restore ResearchMate data.")
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Directory to back up or restore into.",
    )
    parser.add_argument(
        "--archive-key",
        default=None,
        help="Optional OSS/local object key for the backup archive.",
    )
    parser.add_argument(
        "--restore-key",
        default=None,
        help="When set, restore from this archive key instead of creating a backup.",
    )
    parser.add_argument(
        "--target-dir",
        default=None,
        help="Restore destination. Defaults to --data-dir.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    data_dir = Path(args.data_dir)
    if args.restore_key:
        payload = _restore(args.restore_key, Path(args.target_dir or data_dir))
    else:
        payload = _backup(data_dir, archive_key=args.archive_key)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
