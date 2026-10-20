"""Bundled prompt registry — the fallback for `call_llm`.

Per ADR 0004 the *source of truth* for a prompt (and the model that runs
it) is Langfuse: the seam asks Langfuse first and only reads these files
when no registry is configured or the registry is unreachable. Keeping
the seed text in the repo is what lets the vertical slice run before an
operator wires credentials, and it gives reviewers the prompt in a diff.

Layout:

    registry.json              {"prompts": {<prompt_id>: {temperature, max_tokens, ...}}}
    <prompt_id>.md             the system prompt text

**No model name appears in either file.** ADR 0004 makes Langfuse prompt
config the only source of truth for which model runs a prompt: a second,
repo-pinned model would be a routing SSOT with no audit trail, and an
operator who forgot to configure Langfuse would silently get that model
instead of a visible failure. So a seed prompt resolves with
`model=None` and `call_llm` refuses to call a real provider.

The static check in `tests/test_static/test_model_routing.py` fails the
build if a model literal ever appears in `app/**/*.py`.
"""