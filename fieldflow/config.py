from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .auth import AuthConfig, get_auth_config_from_env


@dataclass(frozen=True)
class Settings:
    """Application configuration resolved from environment variables."""

    openapi_spec_path: Path
    target_api_base_url: Optional[str]
    auth_config: Optional[AuthConfig]

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

        return Settings(
            openapi_spec_path=path,
            target_api_base_url=base_url,
            auth_config=auth_config,
        )


settings = Settings.load()
