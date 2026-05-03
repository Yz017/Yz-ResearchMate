from __future__ import annotations

import importlib
import subprocess
import sys


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> None:
    importlib.import_module("researchmate")
    importlib.import_module("researchmate.agent")
    run([sys.executable, "-m", "researchmate.cli.main", "--help"])
    run([sys.executable, "scripts/detect_runtime.py"])


if __name__ == "__main__":
    main()
