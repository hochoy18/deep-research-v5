"""External seams — the only legal path to LLM / search / events / citations.

Per ADR 0003 and the issue #2 acceptance criteria, code outside this package
must not import any LLM provider, web-search provider, Langfuse client, event
channel, or citation parser. The static check in `tests/test_static/` enforces
this rule on every test run.
"""