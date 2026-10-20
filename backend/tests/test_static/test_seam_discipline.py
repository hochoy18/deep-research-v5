"""Static seam-discipline check.

Per ADR 0003 and issue #2 acceptance criteria, code outside the
`app/seams/` package MUST NOT import any LLM provider, web-search provider,
Langfuse client, event channel, or citation parser. This module walks the
backend source tree, parses every `import` statement, and fails the test if
any forbidden import is found outside the seams package.

Whitelist:
- The seams package itself imports freely.
- The static check itself may mention the forbidden module names in strings
  (e.g. the patterns list below).
- `app/seams/stream_event.py` and `app/seams/search_web.py` etc. implement
  the seam and must be allowed to do whatever wiring they eventually need.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Backend root: <repo>/backend/app
BACKEND_APP = Path(__file__).resolve().parents[2] / "app"
SEAMS_DIR = BACKEND_APP / "seams"

# Forbidden top-level imports outside the seams package.
# Matched on the first dotted segment of an `import x` or `from x import y`.
FORBIDDEN_TOP_LEVEL = frozenset(
    {
        # LLM providers
        "openai",
        "anthropic",
        "langchain",
        "langchain_core",
        "langchain_openai",
        "langchain_anthropic",
        "dashscope",  # Bailian primary LLM + search
        "google.generativeai",
        "google_genai",
        "cohere",
        "mistralai",
        # Web-search providers
        "tavily",
        # Observability (Langfuse owns prompt registry + traces)
        "langfuse",
    }
)

# Forbidden sub-paths under otherwise-OK top-level packages.
# E.g. `langchain.chat_models` is reachable as `langchain.chat_models` even
# if `langchain` itself is on the whitelist for some reason. We deny it here
# outright — langchain is forbidden, period.
FORBIDDEN_SUBSTRINGS = frozenset(
    {
        "langchain",
        "openai",
        "anthropic",
        "dashscope",
        "tavily",
        "langfuse",
        "cohere",
        "mistralai",
    }
)


def _walk_python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if p.is_file())


def _is_seam_file(path: Path) -> bool:
    try:
        path.relative_to(SEAMS_DIR)
        return True
    except ValueError:
        return False


def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                # `from . import x` — relative import; module is empty so
                # nothing to forbid.
                continue
            modules.append(node.module)
    return modules


def _is_forbidden(module: str) -> str | None:
    """Return the reason string if `module` is forbidden, else None."""
    if not module:
        return None
    top = module.split(".", 1)[0]
    if top in FORBIDDEN_TOP_LEVEL:
        return f"forbidden top-level import: {module!r}"
    for needle in FORBIDDEN_SUBSTRINGS:
        if needle in module:
            return f"forbidden substring {needle!r} in import: {module!r}"
    return None


def _violations() -> list[tuple[Path, int, str, str]]:
    """Walk every Python file and report forbidden imports outside `seams/`."""
    bad: list[tuple[Path, int, str, str]] = []
    for py in _walk_python_files(BACKEND_APP):
        if _is_seam_file(py):
            continue
        try:
            source = py.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            tree = ast.parse(source, filename=str(py))
        except SyntaxError:
            continue
        for lineno, module in [(n, m) for n, m in enumerate(_imported_modules(tree), 1)]:
            reason = _is_forbidden(module)
            if reason is not None:
                bad.append((py, lineno, module, reason))
    return bad


class TestSeamDiscipline:
    def test_no_forbidden_imports_outside_seams(self) -> None:
        bad = _violations()
        if bad:
            lines = [f"{p.relative_to(BACKEND_APP)}:{ln} {m}  ({r})" for p, ln, m, r in bad]
            pytest.fail(
                "Forbidden imports outside app/seams/:\n  " + "\n  ".join(lines)
            )

    def test_seams_directory_exists(self) -> None:
        assert SEAMS_DIR.is_dir(), f"seams package missing at {SEAMS_DIR}"

    def test_each_seam_has_a_module_file(self) -> None:
        expected = {
            "call_llm",
            "search_web",
            "evaluate",
            "stream_event",
            "extract_citations",
        }
        actual = {p.stem for p in _walk_python_files(SEAMS_DIR) if p.stem != "__init__"}
        assert expected.issubset(actual), (
            f"missing seam files: {expected - actual}"
        )