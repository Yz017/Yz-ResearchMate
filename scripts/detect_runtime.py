from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from researchmate.config import get_settings


@dataclass(frozen=True)
class RuntimeInfo:
    python: str
    torch_installed: bool
    cuda_available: bool
    device_name: str
    embedding_device: str


def detect_runtime() -> RuntimeInfo:
    import platform
    import warnings

    settings = get_settings()
    try:
        import torch
    except ImportError:
        return RuntimeInfo(
            python=platform.python_version(),
            torch_installed=False,
            cuda_available=False,
            device_name="torch not installed",
            embedding_device=settings.embedding_device,
        )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cuda_available = bool(torch.cuda.is_available())
    device_name = torch.cuda.get_device_name(0) if cuda_available else "cpu"
    return RuntimeInfo(
        python=platform.python_version(),
        torch_installed=True,
        cuda_available=cuda_available,
        device_name=device_name,
        embedding_device=settings.embedding_device,
    )


def render_markdown(info: RuntimeInfo) -> str:
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    mode = "GPU" if info.cuda_available else "CPU"
    return "\n".join(
        [
            "# Performance Baseline",
            "",
            f"- Generated at: `{generated_at}`",
            f"- Python: `{info.python}`",
            f"- Torch installed: `{info.torch_installed}`",
            f"- CUDA available: `{info.cuda_available}`",
            f"- Runtime mode: `{mode}`",
            f"- Device: `{info.device_name}`",
            f"- EMBEDDING_DEVICE: `{info.embedding_device}`",
            "",
            "Runtime detection records the current Python/Torch mode. RAG-specific "
            "embedding and retrieval notes are appended in docs/perf_baseline.md.",
            "",
        ]
    )


def main() -> None:
    info = detect_runtime()
    output_path = Path("docs/perf_baseline.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_markdown(info), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
