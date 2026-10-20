"""The module-level `app` that `uvicorn app.main:app` serves.

Every other test builds its app through `create_app(settings)`, so a broken
launch path stays broken until someone runs the server by hand. These tests
pin the one thing uvicorn depends on: importing the module and reading
`app` yields a real application, not `None`.
"""

from __future__ import annotations

import importlib

from fastapi import FastAPI


class TestModuleApp:
    def test_uvicorn_app_attribute_is_a_real_application(self) -> None:
        module = importlib.import_module("app.main")

        assert isinstance(module.app, FastAPI)

    def test_the_app_attribute_is_cached_between_reads(self) -> None:
        """PEP 562 `__getattr__` fires only for names absent from the module
        namespace. Caching the result keeps `create_app()` from running —
        and re-reading the environment — on every access."""
        module = importlib.import_module("app.main")

        assert module.app is module.app