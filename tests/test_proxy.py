from __future__ import annotations

import json
from pathlib import Path

import mcp.types as mcp_types
import pytest

from fieldflow_mcp.proxy.config import Registry, UpstreamEntry, default_config_path
from fieldflow_mcp.proxy.server import (
    FIELDS_PARAM,
    NAMESPACE_SEP,
    _filter_result,
    _split_namespaced,
    _wrap_tool,
)


def test_default_config_path_respects_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FIELDFLOW_CONFIG_HOME", str(tmp_path))
    assert default_config_path() == tmp_path / "proxy.json"


def test_upstream_entry_validates_namespace() -> None:
    with pytest.raises(ValueError):
        UpstreamEntry(namespace="Bad-Name", transport="http", url="https://x")
    with pytest.raises(ValueError):
        UpstreamEntry(namespace="ok", transport="http")  # missing url
    with pytest.raises(ValueError):
        UpstreamEntry(namespace="ok", transport="stdio")  # missing command


def test_registry_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "proxy.json"
    registry = Registry()
    registry.add(
        UpstreamEntry(
            namespace="posthog", transport="http", url="https://mcp.posthog.com/"
        )
    )
    registry.add(
        UpstreamEntry(
            namespace="local",
            transport="stdio",
            command=["npx", "-y", "@some/mcp"],
            env={"FOO": "bar"},
        )
    )
    registry.save(path)

    loaded = Registry.load(path)
    assert set(loaded.upstreams.keys()) == {"posthog", "local"}
    assert loaded.upstreams["posthog"].url == "https://mcp.posthog.com/"
    assert loaded.upstreams["local"].command == ["npx", "-y", "@some/mcp"]
    assert loaded.upstreams["local"].env == {"FOO": "bar"}


def test_registry_load_missing_returns_empty(tmp_path: Path) -> None:
    registry = Registry.load(tmp_path / "nope.json")
    assert registry.upstreams == {}


def test_wrap_tool_injects_fields_and_namespaces() -> None:
    tool = mcp_types.Tool(
        name="query_run",
        description="Run a query",
        inputSchema={
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
        },
        outputSchema={"type": "object"},
    )
    wrapped = _wrap_tool("posthog", tool)
    assert wrapped.name == f"posthog{NAMESPACE_SEP}query_run"
    assert FIELDS_PARAM in wrapped.inputSchema["properties"]
    assert wrapped.inputSchema["properties"]["sql"] == {"type": "string"}
    assert wrapped.outputSchema == {"type": "object"}
    assert "[via fieldflow:posthog]" in (wrapped.description or "")


def test_wrap_tool_warns_on_existing_fields_param(caplog: pytest.LogCaptureFixture) -> None:
    tool = mcp_types.Tool(
        name="t",
        description="",
        inputSchema={
            "type": "object",
            "properties": {"fields": {"type": "string"}},
        },
    )
    with caplog.at_level("WARNING"):
        wrapped = _wrap_tool("ns", tool)
    assert "fields" in wrapped.inputSchema["properties"]
    assert any("already declares a 'fields'" in r.message for r in caplog.records)


def test_split_namespaced() -> None:
    assert _split_namespaced("posthog__query_run") == ("posthog", "query_run")
    assert _split_namespaced("ns__tool_with_underscores") == (
        "ns",
        "tool_with_underscores",
    )
    with pytest.raises(ValueError):
        _split_namespaced("no_namespace")
    with pytest.raises(ValueError):
        _split_namespaced("__missing_ns")


def test_filter_result_filters_structured_content() -> None:
    result = mcp_types.CallToolResult(
        content=[
            mcp_types.TextContent(
                type="text",
                text=json.dumps({"id": 1, "name": "x", "secret": "y"}),
            )
        ],
        structuredContent={"id": 1, "name": "x", "secret": "y"},
    )
    filtered = _filter_result(result, ["id", "name"])
    assert filtered.structuredContent == {"id": 1, "name": "x"}
    decoded = json.loads(filtered.content[0].text)
    assert decoded == {"id": 1, "name": "x"}


def test_filter_result_leaves_non_json_text_alone() -> None:
    result = mcp_types.CallToolResult(
        content=[mcp_types.TextContent(type="text", text="hello world")],
    )
    filtered = _filter_result(result, ["anything"])
    assert filtered.content[0].text == "hello world"


def test_filter_result_passes_through_errors() -> None:
    result = mcp_types.CallToolResult(
        content=[mcp_types.TextContent(type="text", text='{"oops": true}')],
        isError=True,
    )
    filtered = _filter_result(result, ["x"])
    assert filtered is result


def test_filter_result_filters_lists_with_bracket_selector() -> None:
    payload = {"items": [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]}
    result = mcp_types.CallToolResult(
        content=[mcp_types.TextContent(type="text", text=json.dumps(payload))],
        structuredContent=payload,
    )
    filtered = _filter_result(result, ["items[].id"])
    assert filtered.structuredContent == {"items": [{"id": 1}, {"id": 2}]}
