from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from .auth import AuthConfig, AuthProvider
from .field_query import (
    DISCOVERY_ERROR_EXPIRED,
    DISCOVERY_ERROR_NOT_FOUND,
    DISCOVERY_ERROR_OPERATION_MISMATCH,
    FieldDiscoveryCache,
    FieldQueryResolver,
    extract_candidate_paths,
)
from .spec_parser import EndpointOperation

logger = logging.getLogger(__name__)


class APIProxy:
    """Proxy requests from the MCP server to the upstream REST API."""

    def __init__(
        self,
        base_url: str,
        auth_provider: Optional[AuthProvider] = None,
        default_auth_config: Optional[AuthConfig] = None,
        field_query_resolver: Optional[FieldQueryResolver] = None,
        field_discovery_cache: Optional[FieldDiscoveryCache] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth_provider = auth_provider
        self.default_auth_config = default_auth_config
        self.field_query_resolver = field_query_resolver
        self.field_discovery_cache = field_discovery_cache
        self._client: Optional[httpx.AsyncClient] = None

    async def execute(
        self,
        *,
        operation: EndpointOperation,
        path_params: Dict[str, Any],
        query_params: Dict[str, Any],
        body: Optional[Dict[str, Any]],
        path_template: str,
        fields: Optional[List[str]] = None,
        field_query: Optional[str] = None,
        field_query_limit: int = 8,
        discovery_id: Optional[str] = None,
    ) -> Any:
        selector_tree: Optional[FieldSelectorTree] = None
        if fields:
            try:
                selector_tree = build_selector_tree(fields)
            except FieldSelectorError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
        normalized_discovery_id = (
            discovery_id.strip() if isinstance(discovery_id, str) else None
        )
        if normalized_discovery_id:
            data = await self._load_discovery_payload(
                normalized_discovery_id,
                operation_name=operation.name,
            )
        else:
            data = await self._request_upstream_json(
                operation=operation,
                path_params=path_params,
                query_params=query_params,
                body=body,
                path_template=path_template,
            )
        if selector_tree is None and field_query:
            resolved_fields = await resolve_field_query(
                data,
                field_query,
                max_fields=field_query_limit,
                resolver=self.field_query_resolver,
            )
            if resolved_fields:
                selector_tree = build_selector_tree(resolved_fields)
        if selector_tree is None:
            return data
        return self._filter_fields(data, selector_tree)

    async def discover_fields(
        self,
        *,
        operation: EndpointOperation,
        path_params: Dict[str, Any],
        query_params: Dict[str, Any],
        body: Optional[Dict[str, Any]],
        path_template: str,
    ) -> Dict[str, Any]:
        cache = self.field_discovery_cache
        if cache is None:
            raise HTTPException(
                status_code=503,
                detail="Field discovery is disabled. Set FIELD_FLOW_DISCOVERY_ENABLED=true.",
            )
        data = await self._request_upstream_json(
            operation=operation,
            path_params=path_params,
            query_params=query_params,
            body=body,
            path_template=path_template,
        )
        return await cache.create(operation_name=operation.name, data=data)

    def _build_url(self, template: str, path_params: Dict[str, Any]) -> str:
        url = template
        for key, value in path_params.items():
            encoded = quote(str(value), safe="")
            url = url.replace(f"{{{key}}}", encoded)
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

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url)
        return self._client

    async def _request_upstream_json(
        self,
        *,
        operation: EndpointOperation,
        path_params: Dict[str, Any],
        query_params: Dict[str, Any],
        body: Optional[Dict[str, Any]],
        path_template: str,
    ) -> Any:
        url = self._build_url(path_template, path_params)
        method = operation.method.upper()
        request_kwargs = self._build_request_kwargs(operation, query_params, body)
        client = self._get_client()
        response = await client.request(
            method,
            url,
            **request_kwargs,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - error handling
            detail = str(exc)
            headers = request_kwargs.get("headers")
            if self.auth_provider and isinstance(headers, dict):
                for _, value in headers.items():
                    if isinstance(value, str) and value and value in detail:
                        detail = detail.replace(value, "[REDACTED]")
            raise HTTPException(
                status_code=exc.response.status_code, detail=detail
            ) from exc
        if not response.content:
            return {}

        content_type = response.headers.get("content-type", "").lower()
        try:
            return response.json()
        except Exception as exc:
            preview = response.text[:200] if len(response.text) > 200 else response.text
            error_detail = (
                f"Upstream API returned non-JSON response. "
                f"Status: {response.status_code}, "
                f"Content-Type: {content_type or 'not set'}, "
                f"URL: {url}, "
                f"Content preview: {preview}"
            )
            logger.error(error_detail)
            raise HTTPException(status_code=502, detail=error_detail) from exc

    def _build_request_kwargs(
        self,
        operation: EndpointOperation,
        query_params: Dict[str, Any],
        body: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        request_kwargs: Dict[str, Any] = {}
        if query_params:
            request_kwargs["params"] = query_params
        if body is not None:
            request_kwargs["json"] = body

        if self.auth_provider:
            auth_headers = self.auth_provider.get_auth_headers(
                operation, self.default_auth_config
            )
            if auth_headers:
                request_kwargs["headers"] = auth_headers
                sanitized = self.auth_provider.sanitize_headers(auth_headers)
                logger.debug("Adding authentication headers: %s", sanitized)
        return request_kwargs

    async def _load_discovery_payload(
        self,
        discovery_id: str,
        *,
        operation_name: str,
    ) -> Any:
        cache = self.field_discovery_cache
        if cache is None:
            raise HTTPException(
                status_code=503,
                detail="Field discovery is disabled. Set FIELD_FLOW_DISCOVERY_ENABLED=true.",
            )
        payload, error = await cache.load(discovery_id, operation_name=operation_name)
        if error is None:
            return payload
        if error == DISCOVERY_ERROR_EXPIRED:
            detail = (
                "The provided discovery_id has expired. Run the discovery tool again "
                "to refresh candidates."
            )
        elif error == DISCOVERY_ERROR_OPERATION_MISMATCH:
            detail = (
                "The provided discovery_id belongs to a different tool operation and "
                "cannot be reused here."
            )
        elif error == DISCOVERY_ERROR_NOT_FOUND:
            detail = (
                "Unknown discovery_id. Run the discovery tool first, then retry with "
                "the returned discovery_id."
            )
        else:  # pragma: no cover - safeguard
            detail = "Invalid discovery_id."
        raise HTTPException(status_code=422, detail=detail)

    async def aclose(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            close_targets: List[Any] = []
        else:
            close_targets = [client]
        close_targets.append(self.field_query_resolver)
        close_targets.append(self.field_discovery_cache)

        for target in close_targets:
            close_method = getattr(target, "aclose", None)
            if close_method is None:
                continue
            result = close_method()
            if hasattr(result, "__await__"):
                await result


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
                if part[idx : idx + 2] != "[]":
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
        item_node = node.all_items if node.all_items is not None else node
        if item_node is node and not node.keys:
            return _MISSING
        filtered_items: List[Any] = []
        for item in data:
            filtered = apply_selector_tree(item, item_node)
            if filtered is _MISSING:
                continue
            filtered_items.append(filtered)
        return filtered_items

    if node.include_self:
        return data
    return _MISSING


async def resolve_field_query(
    data: Any,
    query: str,
    *,
    max_fields: int = 8,
    resolver: Optional[FieldQueryResolver] = None,
) -> List[str]:
    if resolver is None:
        return []
    try:
        selected = await resolver.resolve(data, query, max_fields=max_fields)
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("field_query resolver failed: %s", exc)
        return []
    if not selected:
        return []

    valid_candidates = set(extract_candidate_paths(data))
    filtered: List[str] = []
    for item in selected:
        if item not in valid_candidates:
            continue
        if item in filtered:
            continue
        filtered.append(item)
        if len(filtered) >= max_fields:
            break
    return filtered
