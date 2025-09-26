from __future__ import annotations

import pytest

from fieldflow.proxy import (
    APIProxy,
    FieldSelectorError,
    apply_selector_tree,
    build_selector_tree,
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


def test_missing_fields_return_empty_structure() -> None:
    data = {"name": "Pikachu"}
    tree = build_selector_tree(["height"])
    proxy = APIProxy(base_url="https://pokeapi.co")
    assert proxy._filter_fields(data, tree) == {}


def test_invalid_selector_raises() -> None:
    with pytest.raises(FieldSelectorError):
        build_selector_tree(["moves[0].move"])
