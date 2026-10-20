"""Cross-layer state — the LangGraph state object and its reducers.

The three layers never import each other (issue #1 §1); they coordinate
through `SessionState` and the five seams.
"""
