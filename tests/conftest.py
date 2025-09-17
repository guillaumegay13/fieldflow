from __future__ import annotations

import sys
from importlib import reload
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture()
def reload_app_modules():
    def _reload() -> None:
        import fieldflow.config
        import fieldflow.http_app
        import fieldflow_mcp.server
        import fieldflow.proxy

        reload(fieldflow.config)
        reload(fieldflow.proxy)
        reload(fieldflow_mcp.server)
        reload(fieldflow.http_app)

    return _reload
