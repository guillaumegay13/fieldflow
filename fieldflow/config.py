from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .auth import AuthConfig, get_auth_config_from_env
from .field_query import FieldDiscoveryConfig, FieldQueryAIConfig


@dataclass(frozen=True)
class Settings:
    """Application configuration resolved from environment variables."""

    openapi_spec_path: Path
    target_api_base_url: Optional[str]
    auth_config: Optional[AuthConfig]
    field_query_ai: FieldQueryAIConfig
    field_discovery: FieldDiscoveryConfig

    @staticmethod
    def load() -> Settings:
        spec_path = (
            os.getenv("FIELD_FLOW_OPENAPI_SPEC_PATH")
            or os.getenv("MCP_PROXY_OPENAPI_SPEC_PATH")
            or "examples/jsonplaceholder_openapi.yaml"
        )
        base_url = os.getenv("FIELD_FLOW_TARGET_API_BASE_URL") or os.getenv(
            "MCP_PROXY_TARGET_API_BASE_URL"
        )
        path = Path(spec_path).expanduser().resolve()

        # Load authentication configuration
        auth_config = get_auth_config_from_env()
        field_query_enabled = os.getenv(
            "FIELD_FLOW_FIELD_QUERY_ENABLED", "false"
        ).lower() not in {"0", "false", "no", "off"}
        field_query_model = os.getenv("FIELD_FLOW_FIELD_QUERY_MODEL")
        field_query_api_key = os.getenv("FIELD_FLOW_FIELD_QUERY_API_KEY") or os.getenv(
            "OPENAI_API_KEY"
        )
        field_query_api_base_url = os.getenv(
            "FIELD_FLOW_FIELD_QUERY_API_BASE_URL", "https://api.openai.com/v1"
        )
        timeout_raw = os.getenv("FIELD_FLOW_FIELD_QUERY_TIMEOUT_SECONDS", "8")
        max_candidates_raw = os.getenv("FIELD_FLOW_FIELD_QUERY_MAX_CANDIDATES", "400")
        preview_max_chars_raw = os.getenv(
            "FIELD_FLOW_FIELD_QUERY_PREVIEW_MAX_CHARS", "12000"
        )
        discovery_enabled = os.getenv(
            "FIELD_FLOW_DISCOVERY_ENABLED", "true"
        ).lower() not in {"0", "false", "no", "off"}
        discovery_ttl_raw = os.getenv("FIELD_FLOW_DISCOVERY_TTL_SECONDS", "180")
        discovery_max_entries_raw = os.getenv("FIELD_FLOW_DISCOVERY_MAX_ENTRIES", "256")
        discovery_max_candidates_raw = os.getenv(
            "FIELD_FLOW_DISCOVERY_MAX_CANDIDATES", "400"
        )
        discovery_preview_max_chars_raw = os.getenv(
            "FIELD_FLOW_DISCOVERY_PREVIEW_MAX_CHARS", "12000"
        )
        discovery_path_max_depth_raw = os.getenv(
            "FIELD_FLOW_DISCOVERY_PATH_MAX_DEPTH", "8"
        )
        discovery_list_sample_size_raw = os.getenv(
            "FIELD_FLOW_DISCOVERY_LIST_SAMPLE_SIZE", "10"
        )

        try:
            timeout_seconds = float(timeout_raw)
        except ValueError:
            timeout_seconds = 8.0
        try:
            max_candidates = int(max_candidates_raw)
        except ValueError:
            max_candidates = 400
        try:
            preview_max_chars = int(preview_max_chars_raw)
        except ValueError:
            preview_max_chars = 12000
        try:
            discovery_ttl_seconds = int(discovery_ttl_raw)
        except ValueError:
            discovery_ttl_seconds = 180
        try:
            discovery_max_entries = int(discovery_max_entries_raw)
        except ValueError:
            discovery_max_entries = 256
        try:
            discovery_max_candidates = int(discovery_max_candidates_raw)
        except ValueError:
            discovery_max_candidates = 400
        try:
            discovery_preview_max_chars = int(discovery_preview_max_chars_raw)
        except ValueError:
            discovery_preview_max_chars = 12000
        try:
            discovery_path_max_depth = int(discovery_path_max_depth_raw)
        except ValueError:
            discovery_path_max_depth = 8
        try:
            discovery_list_sample_size = int(discovery_list_sample_size_raw)
        except ValueError:
            discovery_list_sample_size = 10

        field_query_ai = FieldQueryAIConfig(
            enabled=field_query_enabled,
            model=field_query_model,
            api_key=field_query_api_key,
            api_base_url=field_query_api_base_url,
            timeout_seconds=max(1.0, timeout_seconds),
            max_candidates=max(10, max_candidates),
            preview_max_chars=max(1000, preview_max_chars),
        )
        field_discovery = FieldDiscoveryConfig(
            enabled=discovery_enabled,
            ttl_seconds=max(5, discovery_ttl_seconds),
            max_entries=max(10, discovery_max_entries),
            max_candidates=max(10, discovery_max_candidates),
            preview_max_chars=max(1000, discovery_preview_max_chars),
            path_max_depth=max(1, discovery_path_max_depth),
            list_sample_size=max(1, discovery_list_sample_size),
        )

        return Settings(
            openapi_spec_path=path,
            target_api_base_url=base_url,
            auth_config=auth_config,
            field_query_ai=field_query_ai,
            field_discovery=field_discovery,
        )


settings = Settings.load()
