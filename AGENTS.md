# Repository Guidelines

## Project Structure & Module Organization
- `src/open_deep_research/`: Core package (e.g., `configuration.py`, `deep_researcher.py`, `state.py`, `utils.py`, `prompts.py`).
- `src/legacy/`: Earlier implementations and notebooks; avoid changes unless fixing regressions.
- `tests/`: Pytest-based tests and evaluation utilities; also top-level `test_mcp_*.py` live in the repo root.
- `examples/`: Usage notes and prompt examples.
- `cli_*.py`: Runnable CLI entry points (local, MCP, interactive).

## Build, Test, and Development Commands
- Create env (Python 3.13): `uv venv && . .venv/Scripts/Activate` (Windows) or `source .venv/bin/activate`.
- Install deps: `uv sync` (use `uv pip install -e .[dev]` for dev extras: ruff, mypy).
- Run LangGraph dev server: `uvx --from "langgraph-cli[inmem]" --with-editable . langgraph dev --allow-blocking`.
- Run CLI locally: `python cli_research.py --help` (see other `cli_*.py`).
- Tests: `pytest -q` (runs root tests and `tests/`).
- Lint/format: `ruff check .` and `ruff format .`.
- Type check: `mypy src`.

## Coding Style & Naming Conventions
- Python, 4-space indentation, use type hints in library code.
- Docstrings follow Google style (pydocstyle via ruff); add module/function/class docstrings for public APIs.
- Naming: `snake_case` for functions/vars/modules, `PascalCase` for classes, `SCREAMING_SNAKE_CASE` for constants.
- Avoid `print()` in library code (ruff T201); prefer logging or return values. Keep changes minimal and focused.

## Testing Guidelines
- Use `pytest`; place tests in `tests/` and name `test_*.py`. Root `test_mcp_*.py` are also supported.
- Write unit tests for new behavior and regression tests for bugs. Aim to cover edge cases and error paths.
- Example: `pytest -q tests/test_research_flow.py -k "report or mcp"`.

## Commit & Pull Request Guidelines
- Use Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.
- PRs: include a clear summary, linked issues, reproduction/validation steps, and tests. Add screenshots for UX changes. Note breaking changes explicitly.

## Security & Configuration Tips
- Never commit secrets. Copy `.env.example` to `.env` and set keys (e.g., OpenAI/Anthropic/Tavily). Avoid logging secrets.
- Keep provider/model choices in `src/open_deep_research/configuration.py` or the Studio UI; prefer config over hard-coded values.

## Agent-Specific Instructions
- Respect this file’s scope. Do not reformat unrelated files. Update docs/tests when behavior changes. Prefer small, reviewable diffs.
