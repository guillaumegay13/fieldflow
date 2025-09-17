from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


try:
    import yaml
except Exception:  # pragma: no cover - yaml is optional
    yaml = None  # type: ignore


def load_spec(path: Path) -> Dict[str, Any]:
    """Load an OpenAPI spec from a JSON or YAML file."""

    raw = path.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        if not yaml:
            raise RuntimeError(
                "Failed to parse OpenAPI specification as JSON and PyYAML is not installed."
            )
        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            raise ValueError("OpenAPI specification must decode to an object.")
        return data
