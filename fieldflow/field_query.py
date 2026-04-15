from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, Tuple

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FieldQueryAIConfig:
    enabled: bool
    model: Optional[str]
    api_key: Optional[str]
    api_base_url: str
    timeout_seconds: float
    max_candidates: int
    preview_max_chars: int

    def is_configured(self) -> bool:
        return self.enabled and bool(self.model and self.api_key)


@dataclass(frozen=True)
class FieldDiscoveryConfig:
    enabled: bool
    ttl_seconds: int
    max_entries: int
    max_candidates: int
    preview_max_chars: int
    path_max_depth: int
    list_sample_size: int


class FieldQueryResolver(Protocol):
    async def resolve(self, data: Any, query: str, *, max_fields: int) -> List[str]: ...

    async def aclose(self) -> None: ...


DISCOVERY_ERROR_NOT_FOUND = "not_found"
DISCOVERY_ERROR_EXPIRED = "expired"
DISCOVERY_ERROR_OPERATION_MISMATCH = "operation_mismatch"


@dataclass
class _DiscoveryEntry:
    operation_name: str
    data: Any
    expires_at_epoch: float


class FieldDiscoveryCache:
    """Store discovery payloads so follow-up field selections can avoid a second API call."""

    def __init__(self, config: FieldDiscoveryConfig):
        self.config = config
        self._entries: OrderedDict[str, _DiscoveryEntry] = OrderedDict()
        self._lock = asyncio.Lock()

    async def create(self, *, operation_name: str, data: Any) -> Dict[str, Any]:
        all_candidates = extract_candidate_paths(
            data,
            max_depth=self.config.path_max_depth,
            max_list_items=self.config.list_sample_size,
        )
        candidates = all_candidates[: self.config.max_candidates]
        payload_preview = _build_payload_preview(
            data, max_chars=self.config.preview_max_chars
        )
        now = time.time()
        expires_at_epoch = now + self.config.ttl_seconds
        discovery_id = secrets.token_urlsafe(12)
        entry = _DiscoveryEntry(
            operation_name=operation_name,
            data=data,
            expires_at_epoch=expires_at_epoch,
        )

        async with self._lock:
            self._evict_expired_locked(now)
            while len(self._entries) >= self.config.max_entries:
                self._entries.popitem(last=False)
            self._entries[discovery_id] = entry

        return {
            "discovery_id": discovery_id,
            "operation_name": operation_name,
            "expires_at": _format_utc_timestamp(expires_at_epoch),
            "ttl_seconds": self.config.ttl_seconds,
            "candidate_count": len(all_candidates),
            "candidates": candidates,
            "payload_preview": payload_preview,
        }

    async def load(
        self,
        discovery_id: str,
        *,
        operation_name: str,
    ) -> Tuple[Optional[Any], Optional[str]]:
        now = time.time()
        key = discovery_id.strip()
        if not key:
            return None, DISCOVERY_ERROR_NOT_FOUND

        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._evict_expired_locked(now)
                return None, DISCOVERY_ERROR_NOT_FOUND
            if entry.expires_at_epoch <= now:
                del self._entries[key]
                self._evict_expired_locked(now)
                return None, DISCOVERY_ERROR_EXPIRED
            if entry.operation_name != operation_name:
                return None, DISCOVERY_ERROR_OPERATION_MISMATCH
            self._entries.move_to_end(key)
            return entry.data, None

    async def aclose(self) -> None:
        async with self._lock:
            self._entries.clear()

    def _evict_expired_locked(self, now: float) -> None:
        expired_ids = [
            discovery_id
            for discovery_id, entry in self._entries.items()
            if entry.expires_at_epoch <= now
        ]
        for discovery_id in expired_ids:
            self._entries.pop(discovery_id, None)


class AIFieldQueryResolver:
    """Resolve natural-language field queries with a small LLM."""

    def __init__(self, config: FieldQueryAIConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None

    async def resolve(self, data: Any, query: str, *, max_fields: int) -> List[str]:
        if not self.config.is_configured():
            return []
        normalized_query = query.strip()
        if not normalized_query:
            return []

        candidates = extract_candidate_paths(data)
        if not candidates:
            return []
        candidate_list = candidates[: self.config.max_candidates]

        payload_preview = _build_payload_preview(
            data, max_chars=self.config.preview_max_chars
        )
        prompt = _build_user_prompt(
            query=normalized_query,
            candidates=candidate_list,
            payload_preview=payload_preview,
            max_fields=max_fields,
        )
        raw = await self._request_selection(prompt)
        selected = _parse_selected_fields(raw)
        if not selected:
            return []
        return _sanitize_selected_fields(
            selected,
            candidate_list,
            max_fields=max_fields,
        )

    async def _request_selection(self, prompt: str) -> str:
        client = self._get_client()
        response = await client.post(
            "/chat/completions",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You map user intent to existing JSON field selectors. "
                            "Return ONLY valid JSON with shape "
                            '{"selected_fields": ["field.path", "..."]}. '
                            "Select only from provided candidates. "
                            "Favor recall: include important supporting context when useful "
                            "(identifiers, names, status). Do not invent fields."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            },
        )
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices", [])
        if not choices:
            return ""
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: List[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
            return "".join(chunks)
        return ""

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.api_base_url.rstrip("/"),
                timeout=self.config.timeout_seconds,
            )
        return self._client

    async def aclose(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        await client.aclose()


def create_field_query_resolver(
    config: FieldQueryAIConfig,
) -> Optional[FieldQueryResolver]:
    if not config.enabled:
        return None
    return AIFieldQueryResolver(config)


def create_field_discovery_cache(
    config: FieldDiscoveryConfig,
) -> Optional[FieldDiscoveryCache]:
    if not config.enabled:
        return None
    return FieldDiscoveryCache(config)


def extract_candidate_paths(
    data: Any, *, max_depth: int = 8, max_list_items: int = 10
) -> List[str]:
    result: set[str] = set()

    def walk(value: Any, path: str, depth: int) -> None:
        if depth > max_depth:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                key_path = f"{path}.{key}" if path else key
                result.add(key_path)
                walk(child, key_path, depth + 1)
            return
        if isinstance(value, list):
            list_path = f"{path}[]" if path else "[]"
            result.add(list_path)
            for child in value[:max_list_items]:
                walk(child, list_path, depth + 1)

    walk(data, "", 0)
    return sorted(result)


def _build_payload_preview(data: Any, *, max_chars: int) -> str:
    preview_obj = _compact_value(data, depth=0, max_depth=4, max_list_items=3)
    text = json.dumps(preview_obj, ensure_ascii=True, separators=(",", ":"))
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def _compact_value(
    value: Any, *, depth: int, max_depth: int, max_list_items: int
) -> Any:
    if depth >= max_depth:
        return _summarize_leaf(value)
    if isinstance(value, dict):
        compact: Dict[str, Any] = {}
        for key, child in value.items():
            compact[key] = _compact_value(
                child,
                depth=depth + 1,
                max_depth=max_depth,
                max_list_items=max_list_items,
            )
        return compact
    if isinstance(value, list):
        return [
            _compact_value(
                child,
                depth=depth + 1,
                max_depth=max_depth,
                max_list_items=max_list_items,
            )
            for child in value[:max_list_items]
        ]
    return _summarize_leaf(value)


def _summarize_leaf(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return {"type": "list", "length": len(value)}
    if isinstance(value, dict):
        return {"type": "object", "keys": list(value.keys())[:8]}
    return str(type(value).__name__)


def _build_user_prompt(
    *,
    query: str,
    candidates: List[str],
    payload_preview: str,
    max_fields: int,
) -> str:
    candidate_lines = "\n".join(f"- {item}" for item in candidates)
    return (
        f"User field request:\n{query}\n\n"
        f"Max fields to return: {max_fields}\n\n"
        "Candidate selectors (must choose only from this list):\n"
        f"{candidate_lines}\n\n"
        "Payload preview:\n"
        f"{payload_preview}\n\n"
        "Return JSON only."
    )


def _parse_selected_fields(raw: str) -> List[str]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("field_query model output is not valid JSON")
        return []
    selected = payload.get("selected_fields")
    if not isinstance(selected, list):
        return []
    return [item for item in selected if isinstance(item, str)]


def _sanitize_selected_fields(
    selected: List[str],
    candidates: List[str],
    *,
    max_fields: int,
) -> List[str]:
    candidate_set = set(candidates)
    unique: List[str] = []
    for field in selected:
        if field not in candidate_set:
            continue
        if field in unique:
            continue
        unique.append(field)
        if len(unique) >= max_fields:
            break
    return unique


def _format_utc_timestamp(epoch_seconds: float) -> str:
    stamp = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()
    return stamp.replace("+00:00", "Z")
