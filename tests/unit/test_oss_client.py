from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr

from researchmate.config import Settings
from researchmate.services.oss_client import OssClient, sha256_file


def test_local_oss_roundtrip(tmp_path: Path) -> None:
    settings = Settings(
        RESEARCH_AGENT_TOKEN=SecretStr("x" * 32),
        OSS_LOCAL_DIR=tmp_path / "oss",
    )
    settings.oss_access_key_id = ""
    settings.oss_access_key_secret = SecretStr("")
    settings.oss_bucket = ""
    settings.oss_endpoint = ""
    source = tmp_path / "source.txt"
    source.write_text("researchmate oss roundtrip", encoding="utf-8")

    client = OssClient(settings)
    key = client.put_file(source, key="tests/source.txt")
    downloaded = client.get_file(key, tmp_path / "downloaded.txt")

    assert client.exists(key)
    assert sha256_file(source) == sha256_file(downloaded)
    assert client.sign_url(key).startswith("file://")


def test_default_key_preserves_pdf_suffix(tmp_path: Path) -> None:
    settings = Settings(
        RESEARCH_AGENT_TOKEN=SecretStr("x" * 32),
        OSS_LOCAL_DIR=tmp_path / "oss",
    )
    settings.oss_access_key_id = ""
    settings.oss_access_key_secret = SecretStr("")
    settings.oss_bucket = ""
    settings.oss_endpoint = ""
    source = tmp_path / "rag basics.pdf"
    source.write_bytes(b"%PDF-1.4\n")

    key = OssClient(settings).default_key_for_file(source)

    assert key.endswith("/rag_basics.pdf")
