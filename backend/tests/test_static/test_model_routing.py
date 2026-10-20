"""Static check for ADR 0004: the model name lives in Langfuse config only.

Langfuse is the single source of truth for which model serves a prompt,
so swapping `qwen-plus` for something else is a config change, not a
code change. The failure this prevents is quiet: a hard-coded model in
Python keeps working, so nobody notices routing is no longer centralised.

The same rule applies to `app/prompts/registry.json`. The ADR explicitly
rejected an in-repo config file as a second routing SSOT — it leaves no
audit trail — so the seed registry carries prompt text and generation
parameters only, and a seed prompt resolves with no model at all.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BACKEND_APP = Path(__file__).resolve().parents[2] / "app"
PROMPTS_DIR = BACKEND_APP / "prompts"

# Model identifiers worth matching: vendor prefixes and bare model names
# that would only appear in Python if someone hard-coded routing.
MODEL_NAME = re.compile(
    r"\b(qwen[-\w]*|gpt[-\w.]*|claude[-\w.]*|gemini[-\w.]*|deepseek[-\w]*"
    r"|glm[-\w.]*|moonshot[-\w]*|ernie[-\w.]*)\b",
    re.IGNORECASE,
)

# No Python file is exempt: the seams package forwards a model that came
# from prompt config and must never name one itself.
def _violations() -> list[tuple[Path, int, str]]:
    bad: list[tuple[Path, int, str]] = []
    for py in sorted(BACKEND_APP.rglob("*.py")):
        for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            # Comments explain routing; only executable code is a finding.
            code = line.split("#", 1)[0]
            match = MODEL_NAME.search(code)
            if match:
                bad.append((py, lineno, match.group(0)))
    return bad


class TestModelRouting:
    def test_no_model_name_is_hard_coded_in_python(self) -> None:
        bad = _violations()
        if bad:
            lines = [
                f"{p.relative_to(BACKEND_APP)}:{ln} {name!r} — "
                "per ADR 0004 the model comes from prompt config"
                for p, ln, name in bad
            ]
            pytest.fail("Hard-coded model name(s):\n  " + "\n  ".join(lines))

    def test_seed_registry_declares_no_model(self) -> None:
        """The other side of the rule, asserted in reverse: the in-repo
        fallback must not become a second source of model routing."""
        registry = (PROMPTS_DIR / "registry.json").read_text(encoding="utf-8")
        assert '"model"' not in registry