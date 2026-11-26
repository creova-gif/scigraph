# Contributing to SciGraph

Thank you for your interest in contributing to SciGraph! Please follow these guidelines to keep the codebase deterministic, strictly typed, and easy to review.

## Development Setup

SciGraph targets **Python 3.12+** and uses [`uv`](https://docs.astral.sh/uv/) for environment and dependency management.

```bash
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Quality Gates

Every change must pass all three quality gates before opening or merging a pull request:

```bash
.venv/bin/ruff check src tests
.venv/bin/mypy --strict src tests
.venv/bin/pytest -v
```

### Coding Standards

- **Python 3.12+** with strict type annotations (`mypy --strict`).
- **Pydantic v2** for data models (prefer `ConfigDict(strict=True, frozen=True, extra="forbid")` where appropriate).
- **No bare `except Exception: pass`** — handle or propagate errors explicitly.
- **No inline imports** — place all imports at the top of the module.
- **Deterministic unit tests** — every feature or bug fix must include deterministic unit tests under `tests/`.

## Architecture Decision Records (ADRs)

Record every non-trivial architectural or design choice in `docs/adr/` using [`docs/adr/000-template.md`](docs/adr/000-template.md) before or alongside your implementation.

## Pull Request Guidelines

1. Create a focused branch from `main` and keep diffs scoped to the task.
2. Run `ruff check src tests`, `mypy --strict src tests`, and `pytest -v` locally after your final edit.
3. Never commit `.env` files, API keys, credentials, or PII/PHI fixtures.
4. Complete the checklist in [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md).
