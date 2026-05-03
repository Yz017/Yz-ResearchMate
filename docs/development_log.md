# Development Log

## 2026-05-02 · M0 Project Initialization

### Scope

- Initialized the repository on branch `main`.
- Added `src/` layout package skeleton for `researchmate`.
- Added `pyproject.toml`, `.python-version`, `.gitignore`, `.env.example`, and `uv.lock`.
- Added Pydantic Settings in `src/researchmate/config.py`.
- Added minimal ADK `root_agent` in `src/researchmate/agent.py` using `LlmAgent` + `LiteLlm`.
- Added a Typer CLI entry point: `rmcli`.
- Added a minimal FastAPI shell exporting `researchmate.api:app`.
- Added runtime detection script and generated `docs/perf_baseline.md`.
- Added ruff, black, mypy, pytest, pre-commit, and GitHub Actions CI configuration.
- Added M0 unit tests and smoke test script.
- Added `scripts/check_deepseek_hello.py` for no-secret DeepSeek/LiteLLM hello validation.

### Notes

- `DEEPSEEK_API_KEY` is intentionally never printed, copied, summarized, or recorded. The local key was validated only by a successful model response check.
- `torch` is not installed by default in M0. The runtime baseline records CPU mode and leaves embedding throughput for M1.
- This environment blocks home-directory caches, so tests were run with `UV_CACHE_DIR=.uv-cache`; pre-commit was installed with `PRE_COMMIT_HOME=.pre-commit-cache`.
- This environment also blocks reliable browser automation for `adk web`. M0 therefore verifies `adk web` startup from the server log, app discovery through ADK's loader, and the hello-world LLM turn through ADK Runner.
- LiteLLM is constrained to safe current releases (`>=1.83`) because ADK documentation flags LiteLLM `1.82.7` and `1.82.8` as compromised releases.

### Test Methods

All commands were run from the project root.

```bash
UV_CACHE_DIR=.uv-cache uv sync
```

Result: passed. Resolved 262 packages and installed 206 packages. Generated `uv.lock`.

```bash
UV_CACHE_DIR=.uv-cache uv run python -c "import researchmate; print(researchmate.__version__)"
```

Result: passed. Output: `0.1.0`.

```bash
UV_CACHE_DIR=.uv-cache uv run python -c "from researchmate.agent import root_agent; print(root_agent.name)"
```

Result: passed. Output: `researchmate`.

```bash
UV_CACHE_DIR=.uv-cache uv run rmcli --help
```

Result: passed. Typer help showed `config` and `hello` commands.

```bash
UV_CACHE_DIR=.uv-cache uv run rmcli config
```

Result: passed. Confirmed local settings load. Secret values were not printed.

```bash
UV_CACHE_DIR=.uv-cache timeout 90s uv run python scripts/check_deepseek_hello.py
```

Result: passed. The `researchmate` root agent received a text response from DeepSeek through LiteLLM. Neither the model text nor any `.env` value was printed or persisted.

```bash
UV_CACHE_DIR=.uv-cache uv run python scripts/detect_runtime.py
```

Result: passed. Generated `docs/perf_baseline.md`.

```bash
UV_CACHE_DIR=.uv-cache uv run ruff check .
```

Result: passed. Output: `All checks passed!`

```bash
UV_CACHE_DIR=.uv-cache uv run black --check .
```

Result: passed. Output: `41 files would be left unchanged.`

```bash
UV_CACHE_DIR=.uv-cache uv run mypy
```

Result: passed. Output: `Success: no issues found in 41 source files`.

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/
```

Result: passed. Output: `8 passed in 14.25s`.

```bash
UV_CACHE_DIR=.uv-cache uv run python scripts/smoke_test.py
```

Result: passed. Covered package import, ADK agent import, CLI help, and runtime baseline generation.

```bash
UV_CACHE_DIR=.uv-cache PRE_COMMIT_HOME=.pre-commit-cache uv run pre-commit install
```

Result: passed. Hook installed at `.git/hooks/pre-commit`.

```bash
UV_CACHE_DIR=.uv-cache uv run adk web --session_service_uri=memory:// --artifact_service_uri=memory:// --port 18001 --no-reload src/
```

Result: startup passed. ADK reported:

```text
ADK Web Server started
For local testing, access at http://127.0.0.1:18001.
Uvicorn running on http://127.0.0.1:18001
```

The server was stopped with `Ctrl-C` after startup verification.

```bash
UV_CACHE_DIR=.uv-cache timeout 20s uv run adk web --session_service_uri=memory:// --artifact_service_uri=memory:// --port 18002 --no-reload src/
```

Result: startup passed again after DeepSeek configuration. ADK reported the web server started at `http://127.0.0.1:18002`, then the process was stopped by `timeout`.

```bash
UV_CACHE_DIR=.uv-cache uv run python -c "from google.adk.cli.utils.agent_loader import AgentLoader; apps = AgentLoader('src').list_agents(); assert apps == ['researchmate'], apps"
```

Result: passed. ADK can discover the `researchmate` app from `src/`.
