from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fieldflow.proxy import APIProxy
from fieldflow_mcp import server as mcp_server

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_SPEC = PROJECT_ROOT / "examples" / "jsonplaceholder_openapi.yaml"


@pytest.mark.asyncio
async def test_create_mcp_server_registers_tools(monkeypatch: pytest.MonkeyPatch, reload_app_modules):
    monkeypatch.setenv("FIELD_FLOW_OPENAPI_SPEC_PATH", str(EXAMPLE_SPEC))
    monkeypatch.delenv("FIELD_FLOW_TARGET_API_BASE_URL", raising=False)

    captured: dict[str, Any] = {}

    async def fake_execute(self, **kwargs: Any) -> Any:
        captured["kwargs"] = kwargs
        return {"name": "Mock", "email": "mock@example.com"}

    reload_app_modules()
    monkeypatch.setattr(APIProxy, "execute", fake_execute, raising=False)
    import fieldflow.proxy as proxy_module
    monkeypatch.setattr(proxy_module.APIProxy, "execute", fake_execute, raising=False)

    server = mcp_server.create_mcp_server()
    tool_names = [tool.name for tool in server._tool_manager.list_tools()]
    assert "get_user_info" in tool_names

    result = await server._tool_manager.call_tool(
        "get_user_info",
        {"user_id": 1, "fields": ["name", "email"]},
    )

    assert result == {"name": "Mock", "email": "mock@example.com"}
    assert captured["kwargs"]["path_params"] == {"user_id": 1}
    assert captured["kwargs"]["query_params"] == {}
    assert captured["kwargs"]["fields"] == ["name", "email"]
