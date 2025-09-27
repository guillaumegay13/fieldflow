from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import HTTPException

from .auth import AuthProvider
from .spec_parser import EndpointOperation

logger = logging.getLogger(__name__)


class APIProxy:
    """Proxy requests from the MCP server to the upstream REST API."""

    def __init__(self, base_url: str, auth_provider: Optional[AuthProvider] = None):
        self.base_url = base_url.rstrip("/")
        self.auth_provider = auth_provider

    async def execute(
        self,
        *,
        operation: EndpointOperation,
        path_params: Dict[str, Any],
        query_params: Dict[str, Any],
        body: Optional[Dict[str, Any]],
        fields: Optional[List[str]],
        path_template: str,
    ) -> Any:
        selector_tree: Optional[FieldSelectorTree] = None
        if fields:
            try:
                selector_tree = build_selector_tree(fields)
            except FieldSelectorError as exc:
                raise HTTPException(status_code=422, detail=str(exc))

        url = self._build_url(path_template, path_params)
        method = operation.method.upper()
        request_kwargs: Dict[str, Any] = {}
        if query_params:
            request_kwargs["params"] = query_params
        if body is not None:
            request_kwargs["json"] = body

        # Add authentication headers if available
        if self.auth_provider:
            auth_headers = self.auth_provider.get_auth_headers(operation)
            if auth_headers:
                request_kwargs["headers"] = auth_headers
                # Log that we're authenticating without exposing credentials
                sanitized = self.auth_provider.sanitize_headers(auth_headers)
                logger.debug(f"Adding authentication headers: {sanitized}")

        async with httpx.AsyncClient(base_url=self.base_url) as client:
            response = await client.request(
                method,
                url,
                **request_kwargs,
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - error handling
            # Sanitize any auth headers from error messages
            detail = str(exc)
            if self.auth_provider and request_kwargs.get("headers"):
                for key, value in request_kwargs["headers"].items():
                    if value in detail:
                        detail = detail.replace(value, "[REDACTED]")
            raise HTTPException(
                status_code=exc.response.status_code, detail=detail
            ) from exc
        if not response.content:
            return {}
        data = response.json()
        if selector_tree is None:
            return data
        return self._filter_fields(data, selector_tree)

    def _build_url(self, template: str, path_params: Dict[str, Any]) -> str:
        url = template
        for key, value in path_params.items():
            url = url.replace(f"{{{key}}}", str(value))
        return url

    def _filter_fields(self, data: Any, selector_tree: "FieldSelectorTree") -> Any:
        filtered = apply_selector_tree(data, selector_tree)
        if filtered is _MISSING:
            if isinstance(data, dict):
                return {}
            if isinstance(data, list):
                return []
            return None
        return filtered


class FieldSelectorError(ValueError):
    """Raised when a requested field selector is malformed."""


@dataclass
class FieldSelectorNode:
    include_self: bool = False
    keys: Dict[str, "FieldSelectorNode"] = field(default_factory=dict)
    all_items: Optional["FieldSelectorNode"] = None


FieldSelectorTree = FieldSelectorNode

_MISSING = object()


def build_selector_tree(selectors: List[str]) -> FieldSelectorTree:
    if not selectors:
        raise FieldSelectorError("At least one field must be requested.")
    root = FieldSelectorNode()
    for raw in selectors:
        tokens = _tokenize_selector(raw)
        if not tokens:
            raise FieldSelectorError("Field selector cannot be empty.")
        _add_tokens(root, tokens)
    return root


Token = Tuple[str, Optional[str]]


def _tokenize_selector(selector: str) -> List[Token]:
    if not selector or selector.strip() == "":
        raise FieldSelectorError("Field selector cannot be empty.")
    parts = selector.split(".")
    tokens: List[Token] = []
    for part in parts:
        if part == "":
            raise FieldSelectorError(f"Invalid field selector '{selector}'.")
        idx = 0
        length = len(part)
        while idx < length:
            char = part[idx]
            if char == "[":
                if part[idx: idx + 2] != "[]":
                    raise FieldSelectorError(
                        f"Only '[]' list selectors are supported ('{selector}')."
                    )
                tokens.append(("all", None))
                idx += 2
            else:
                next_idx = part.find("[", idx)
                if next_idx == -1:
                    key = part[idx:]
                    if key == "":
                        raise FieldSelectorError(
                            f"Invalid field selector '{selector}'."
                        )
                    tokens.append(("key", key))
                    idx = length
                else:
                    key = part[idx:next_idx]
                    if key == "":
                        raise FieldSelectorError(
                            f"Invalid field selector '{selector}'."
                        )
                    tokens.append(("key", key))
                    idx = next_idx
    return tokens


def _add_tokens(node: FieldSelectorNode, tokens: List[Token]) -> None:
    if not tokens:
        node.include_self = True
        return
    token, *rest = tokens
    kind, value = token
    if kind == "key":
        assert value is not None
        child = node.keys.get(value)
        if child is None:
            child = FieldSelectorNode()
            node.keys[value] = child
        _add_tokens(child, rest)
    elif kind == "all":
        if node.all_items is None:
            node.all_items = FieldSelectorNode()
        _add_tokens(node.all_items, rest)
    else:  # pragma: no cover - safeguard for future token types
        raise FieldSelectorError("Unsupported selector token type.")


def apply_selector_tree(data: Any, node: FieldSelectorNode) -> Any:
    if node.include_self and not node.keys and node.all_items is None:
        return data

    if isinstance(data, dict):
        if node.include_self:
            return data
        result: Dict[str, Any] = {}
        for key, child in node.keys.items():
            if key not in data:
                continue
            filtered_value = apply_selector_tree(data[key], child)
            if filtered_value is not _MISSING:
                result[key] = filtered_value
        if result:
            return result
        return _MISSING

    if isinstance(data, list):
        if node.include_self:
            return data
        if node.all_items is None:
            return _MISSING
        filtered_items: List[Any] = []
        for item in data:
            filtered = apply_selector_tree(item, node.all_items)
            if filtered is _MISSING:
                continue
            filtered_items.append(filtered)
        return filtered_items

    if node.include_self:
        return data
    return _MISSING
