"""FieldFlow core package."""

from .openapi_loader import load_spec
from .tooling import build_request_model


def create_fastapi_app():
    from .http_app import create_fastapi_app as _create_fastapi_app

    return _create_fastapi_app()


__all__ = [
    "build_request_model",
    "create_fastapi_app",
    "load_spec",
]
