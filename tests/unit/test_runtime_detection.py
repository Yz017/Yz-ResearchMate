from __future__ import annotations

from scripts.detect_runtime import detect_runtime, render_markdown


def test_runtime_detection_renders_baseline() -> None:
    info = detect_runtime()
    markdown = render_markdown(info)

    assert "# Performance Baseline" in markdown
    assert "Runtime mode" in markdown
