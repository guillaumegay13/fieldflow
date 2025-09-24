from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import httpx
from httpx import ASGITransport, AsyncClient as HTTPXAsyncClient
import pytest
from fieldflow import proxy as fieldflow_proxy
from fieldflow.http_app import create_fastapi_app

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_SPEC = PROJECT_ROOT / "examples" / "jsonplaceholder_openapi.yaml"


class StubAsyncClient:
    """Minimal async client that supplies queued JSON responses."""

    queue: List[Any] = []
    calls: List[Dict[str, Any]] = []

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def __aenter__(self) -> "StubAsyncClient":
        return self

    async def __aexit__(
        self, exc_type, exc, tb
    ) -> None:  # pragma: no cover - cleanup has no logic
        return None

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append(
            {"method": method, "url": url, "kwargs": kwargs, "base_url": self.base_url}
        )
        payload = self.queue.pop(0)
        request = httpx.Request(method, f"{self.base_url}{url}")
        return httpx.Response(200, request=request, json=payload)


@pytest.fixture(autouse=True)
def _reset_stub_state():
    StubAsyncClient.queue = []
    StubAsyncClient.calls = []
    yield
    StubAsyncClient.queue = []
    StubAsyncClient.calls = []


@pytest.fixture()
def app_instance(monkeypatch: pytest.MonkeyPatch, reload_app_modules):
    monkeypatch.setenv("FIELD_FLOW_OPENAPI_SPEC_PATH", str(EXAMPLE_SPEC))
    monkeypatch.delenv("FIELD_FLOW_TARGET_API_BASE_URL", raising=False)

    reload_app_modules()

    monkeypatch.setattr(fieldflow_proxy.httpx, "AsyncClient", StubAsyncClient)
    return create_fastapi_app()


@pytest.mark.asyncio
async def test_get_user_info_filters_fields(app_instance):
    StubAsyncClient.queue.append(
        {
            "id": 1,
            "name": "Leanne Graham",
            "email": "Sincere@april.biz",
            "username": "Bret",
        }
    )

    async with HTTPXAsyncClient(
        transport=ASGITransport(app=app_instance), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/tools/get_user_info",
            json={"user_id": 1, "fields": ["name", "email"]},
        )

    assert response.status_code == 200
    assert response.json() == {"name": "Leanne Graham", "email": "Sincere@april.biz"}

    call = StubAsyncClient.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == "/users/1"
    assert call["kwargs"] == {}


@pytest.mark.asyncio
async def test_list_posts_preserves_query_params(app_instance):
    StubAsyncClient.queue.append(
        [
            {"userId": 1, "id": 1, "title": "Alpha", "body": "irrelevant"},
            {"userId": 1, "id": 2, "title": "Beta", "body": "ignored"},
        ]
    )

    async with HTTPXAsyncClient(
        transport=ASGITransport(app=app_instance), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/tools/list_posts",
            json={"userId": 1, "fields": ["id", "title"]},
        )

    assert response.status_code == 200
    assert response.json() == [
        {"id": 1, "title": "Alpha"},
        {"id": 2, "title": "Beta"},
    ]

    call = StubAsyncClient.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == "/posts"
    assert call["kwargs"].get("params") == {"userId": 1}
    assert "json" not in call["kwargs"]
