from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Settings:
    """Application configuration resolved from environment variables."""

    openapi_spec_path: Path
    target_api_base_url: Optional[str]

    @staticmethod
    def load() -> Settings:
        spec_path = os.getenv("FIELD_FLOW_OPENAPI_SPEC_PATH", "examples/jsonplaceholder_openapi.yaml")
        base_url = os.getenv("FIELD_FLOW_TARGET_API_BASE_URL")
        path = Path(spec_path).expanduser().resolve()
        return Settings(openapi_spec_path=path, target_api_base_url=base_url)


settings = Settings.load()
