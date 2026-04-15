from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import httpx
from httpx import ASGITransport, AsyncClient as HTTPXAsyncClient
import pytest
import fieldflow.http_app as http_app_module
from fieldflow import proxy as fieldflow_proxy
from fieldflow.http_app import create_fastapi_app

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_SPEC = PROJECT_ROOT / "examples" / "jsonplaceholder_openapi.yaml"


class StubAsyncClient:
    """Minimal async client that supplies queued JSON responses."""

    queue: List[Any] = []
    calls: List[Dict[str, Any]] = []
    init_count: int = 0

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.__class__.init_count += 1

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


class StubFieldQueryResolver:
    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    async def resolve(self, data: Any, query: str, *, max_fields: int) -> List[str]:
        self.calls.append({"query": query, "max_fields": max_fields, "data": data})
        normalized = query.lower()
        if "mail" in normalized:
            return ["email", "id", "unknown"]
        return []

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_stub_state():
    StubAsyncClient.queue = []
    StubAsyncClient.calls = []
    StubAsyncClient.init_count = 0
    yield
    StubAsyncClient.queue = []
    StubAsyncClient.calls = []
    StubAsyncClient.init_count = 0


@pytest.fixture()
def app_instance(monkeypatch: pytest.MonkeyPatch, reload_app_modules):
    monkeypatch.setenv("FIELD_FLOW_OPENAPI_SPEC_PATH", str(EXAMPLE_SPEC))
    monkeypatch.delenv("FIELD_FLOW_TARGET_API_BASE_URL", raising=False)

    reload_app_modules()

    monkeypatch.setattr(fieldflow_proxy.httpx, "AsyncClient", StubAsyncClient)
    return create_fastapi_app()


@pytest.fixture()
def app_instance_with_field_query(monkeypatch: pytest.MonkeyPatch, reload_app_modules):
    monkeypatch.setenv("FIELD_FLOW_OPENAPI_SPEC_PATH", str(EXAMPLE_SPEC))
    monkeypatch.delenv("FIELD_FLOW_TARGET_API_BASE_URL", raising=False)

    reload_app_modules()

    resolver = StubFieldQueryResolver()
    monkeypatch.setattr(fieldflow_proxy.httpx, "AsyncClient", StubAsyncClient)
    monkeypatch.setattr(
        http_app_module,
        "create_field_query_resolver",
        lambda config: resolver,
    )
    return create_fastapi_app(), resolver


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


@pytest.mark.asyncio
async def test_proxy_reuses_http_client_between_requests(app_instance):
    StubAsyncClient.queue.append({"id": 1, "name": "Leanne", "email": "a@b.com"})
    StubAsyncClient.queue.append({"id": 2, "name": "Ervin", "email": "c@d.com"})

    async with HTTPXAsyncClient(
        transport=ASGITransport(app=app_instance), base_url="http://testserver"
    ) as client:
        response_one = await client.post(
            "/tools/get_user_info",
            json={"user_id": 1, "fields": ["id"]},
        )
        response_two = await client.post(
            "/tools/get_user_info",
            json={"user_id": 2, "fields": ["id"]},
        )

    assert response_one.status_code == 200
    assert response_two.status_code == 200
    assert StubAsyncClient.init_count == 1


@pytest.mark.asyncio
async def test_field_query_selects_ai_selected_fields(app_instance_with_field_query):
    app_instance, resolver = app_instance_with_field_query
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
            json={"user_id": 1, "field_query": "mail"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == "Sincere@april.biz"
    assert payload["id"] == 1
    assert payload.keys() == {"email", "id"}
    assert len(resolver.calls) == 1
    assert resolver.calls[0]["query"] == "mail"


@pytest.mark.asyncio
async def test_field_query_returns_full_payload_when_resolver_returns_empty(
    app_instance_with_field_query,
):
    app_instance, resolver = app_instance_with_field_query
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
            json={"user_id": 1, "field_query": "completely unknown thing"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert "id" in payload
    assert "name" in payload
    assert len(resolver.calls) == 1


@pytest.mark.asyncio
async def test_discovery_endpoint_returns_candidates_and_cached_lookup(app_instance):
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
        discovery_response = await client.post(
            "/tools/get_user_info/discover-fields",
            json={"user_id": 1},
        )
        assert discovery_response.status_code == 200
        discovery_payload = discovery_response.json()
        assert "discovery_id" in discovery_payload
        assert "email" in discovery_payload["candidates"]

        response = await client.post(
            "/tools/get_user_info",
            json={
                "user_id": 1,
                "discovery_id": discovery_payload["discovery_id"],
                "fields": ["email"],
            },
        )

    assert response.status_code == 200
    assert response.json() == {"email": "Sincere@april.biz"}
    assert len(StubAsyncClient.calls) == 1
    assert StubAsyncClient.calls[0]["url"] == "/users/1"


@pytest.mark.asyncio
async def test_discovery_id_unknown_returns_422(app_instance):
    async with HTTPXAsyncClient(
        transport=ASGITransport(app=app_instance), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/tools/get_user_info",
            json={"user_id": 1, "discovery_id": "missing-id", "fields": ["email"]},
        )

    assert response.status_code == 422
    assert "discovery_id" in response.json()["detail"]
