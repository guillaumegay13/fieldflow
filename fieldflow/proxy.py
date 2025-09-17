from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException

from .spec_parser import EndpointOperation


class APIProxy:
    """Proxy requests from the MCP server to the upstream REST API."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

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
        url = self._build_url(path_template, path_params)
        method = operation.method.upper()
        request_kwargs: Dict[str, Any] = {}
        if query_params:
            request_kwargs["params"] = query_params
        if body is not None:
            request_kwargs["json"] = body
        async with httpx.AsyncClient(base_url=self.base_url) as client:
            response = await client.request(
                method,
                url,
                **request_kwargs,
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - error handling
            raise HTTPException(status_code=exc.response.status_code, detail=str(exc)) from exc
        if not response.content:
            return {}
        data = response.json()
        return self._filter_fields(data, fields)

    def _build_url(self, template: str, path_params: Dict[str, Any]) -> str:
        url = template
        for key, value in path_params.items():
            url = url.replace(f"{{{key}}}", str(value))
        return url

    def _filter_fields(self, data: Any, fields: Optional[List[str]]) -> Any:
        if not fields:
            return data
        if isinstance(data, list):
            return [self._filter_fields(item, fields) for item in data]
        if isinstance(data, dict):
            return {field: data.get(field) for field in fields if field in data}
        return data
