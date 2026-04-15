from __future__ import annotations

import pytest

from fieldflow import proxy as proxy_module
from fieldflow.field_query import (
    DISCOVERY_ERROR_OPERATION_MISMATCH,
    FieldDiscoveryCache,
    FieldDiscoveryConfig,
    extract_candidate_paths,
)
from fieldflow.proxy import (
    APIProxy,
    apply_selector_tree,
    build_selector_tree,
    resolve_field_query,
)


def test_simple_field_selection() -> None:
    data = {"name": "Pikachu", "height": 4}
    tree = build_selector_tree(["name"])
    filtered = apply_selector_tree(data, tree)
    assert filtered == {"name": "Pikachu"}


def test_nested_field_selection() -> None:
    data = {
        "stats": {
            "attack": {"base_stat": 84, "effort": 0},
            "defense": {"base_stat": 78, "effort": 0},
        },
        "weight": 1220,
    }
    tree = build_selector_tree(["stats.attack.base_stat"])
    filtered = apply_selector_tree(data, tree)
    assert filtered == {"stats": {"attack": {"base_stat": 84}}}


def test_list_field_selection_with_wildcard() -> None:
    data = {
        "moves": [
            {
                "move": {"name": "Thunder Punch", "url": "https://pokeapi.co/move/9/"},
                "learned_by": "pikachu",
            },
            {
                "move": {"name": "Quick Attack", "url": "https://pokeapi.co/move/98/"},
                "learned_by": "pikachu",
            },
        ],
        "name": "pikachu",
    }
    tree = build_selector_tree(["moves[].move.name"])
    filtered = apply_selector_tree(data, tree)
    assert filtered == {
        "moves": [
            {"move": {"name": "Thunder Punch"}},
            {"move": {"name": "Quick Attack"}},
        ]
    }


def test_list_field_selection_returns_full_items_when_requested() -> None:
    data = {
        "moves": [
            {"move": {"name": "Thunderbolt"}},
            {"move": {"name": "Iron Tail"}},
        ]
    }
    tree = build_selector_tree(["moves[]"])
    filtered = apply_selector_tree(data, tree)
    assert filtered == {
        "moves": [
            {"move": {"name": "Thunderbolt"}},
            {"move": {"name": "Iron Tail"}},
        ]
    }


def test_root_list_selection() -> None:
    data = [
        {"name": "Pikachu", "height": 4},
        {"name": "Bulbasaur", "height": 7},
    ]
    tree = build_selector_tree(["[].name"])
    filtered = apply_selector_tree(data, tree)
    assert filtered == [
        {"name": "Pikachu"},
        {"name": "Bulbasaur"},
    ]


def test_root_list_selection_without_wildcard() -> None:
    data = [
        {"name": "Pikachu", "height": 4},
        {"name": "Bulbasaur", "height": 7},
    ]
    tree = build_selector_tree(["name"])
    filtered = apply_selector_tree(data, tree)
    assert filtered == [
        {"name": "Pikachu"},
        {"name": "Bulbasaur"},
    ]


def test_missing_fields_return_empty_structure() -> None:
    data = {"name": "Pikachu"}
    tree = build_selector_tree(["height"])
    proxy = APIProxy(base_url="https://pokeapi.co")
    assert proxy._filter_fields(data, tree) == {}


def test_invalid_selector_raises() -> None:
    with pytest.raises(proxy_module.FieldSelectorError):
        proxy_module.build_selector_tree(["moves[0].move"])


def test_build_url_encodes_path_parameters() -> None:
    proxy = APIProxy(base_url="https://pokeapi.co")
    url = proxy._build_url(
        "/users/{user_id}/repos/{repo}",
        {"user_id": "alice/bob", "repo": "hello world"},
    )
    assert url == "/users/alice%2Fbob/repos/hello%20world"


def test_extract_candidate_paths_includes_nested_and_list_paths() -> None:
    data = {
        "id": 1,
        "moves": [
            {"move": {"name": "Thunder Punch", "url": "https://pokeapi.co/move/9/"}}
        ],
    }
    candidates = extract_candidate_paths(data)
    assert "id" in candidates
    assert "moves" in candidates
    assert "moves[]" in candidates
    assert "moves[].move.name" in candidates


class StubResolver:
    def __init__(self, selected: list[str]):
        self.selected = selected
        self.calls: list[tuple[str, int]] = []

    async def resolve(self, data, query: str, *, max_fields: int) -> list[str]:
        self.calls.append((query, max_fields))
        return self.selected

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_resolve_field_query_uses_resolver_and_filters_invalid_fields() -> None:
    data = {"name": "Leanne Graham", "email": "Sincere@april.biz"}
    resolver = StubResolver(["email", "unknown", "email"])
    resolved = await resolve_field_query(
        data,
        "mail",
        max_fields=5,
        resolver=resolver,
    )
    assert resolved == ["email"]
    assert resolver.calls == [("mail", 5)]


@pytest.mark.asyncio
async def test_resolve_field_query_without_resolver_returns_empty() -> None:
    data = {"name": "Leanne Graham", "email": "Sincere@april.biz"}
    resolved = await resolve_field_query(data, "mail", max_fields=5, resolver=None)
    assert resolved == []


@pytest.mark.asyncio
async def test_field_discovery_cache_create_and_load_round_trip() -> None:
    cache = FieldDiscoveryCache(
        FieldDiscoveryConfig(
            enabled=True,
            ttl_seconds=120,
            max_entries=16,
            max_candidates=32,
            preview_max_chars=2000,
            path_max_depth=8,
            list_sample_size=5,
        )
    )
    data = {"id": 1, "name": "Leanne Graham", "email": "Sincere@april.biz"}
    discovery = await cache.create(operation_name="get_user_info", data=data)
    assert "discovery_id" in discovery
    assert "email" in discovery["candidates"]

    loaded, error = await cache.load(
        discovery["discovery_id"], operation_name="get_user_info"
    )
    assert error is None
    assert loaded == data


@pytest.mark.asyncio
async def test_field_discovery_cache_rejects_operation_mismatch() -> None:
    cache = FieldDiscoveryCache(
        FieldDiscoveryConfig(
            enabled=True,
            ttl_seconds=120,
            max_entries=16,
            max_candidates=32,
            preview_max_chars=2000,
            path_max_depth=8,
            list_sample_size=5,
        )
    )
    discovery = await cache.create(
        operation_name="get_user_info",
        data={"email": "a@b.com"},
    )
    loaded, error = await cache.load(
        discovery["discovery_id"], operation_name="list_posts"
    )
    assert loaded is None
    assert error == DISCOVERY_ERROR_OPERATION_MISMATCH
