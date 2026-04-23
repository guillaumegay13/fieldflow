from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Sequence

from .proxy import FieldSelectorError, filter_data_fields


class CLICommandError(RuntimeError):
    """Raised when a wrapped CLI command cannot produce a usable JSON payload."""

    def __init__(self, payload: dict[str, Any], exit_code: int):
        super().__init__(payload.get("error", "CLI command failed"))
        self.payload = payload
        self.exit_code = exit_code


def run_json_command(
    *,
    command: Sequence[str],
    fields: Sequence[str] | None = None,
    max_items: int | None = None,
) -> dict[str, Any]:
    if not command:
        raise ValueError("A wrapped command is required.")
    if max_items is not None and max_items < 1:
        raise ValueError("--max-items must be greater than 0.")
    command_list, data, stderr_preview = _load_json_command_output(command)

    input_items = len(data) if isinstance(data, list) else None
    reduced = _limit_items(data, max_items)
    if fields:
        try:
            reduced = filter_data_fields(reduced, list(fields))
        except FieldSelectorError as exc:
            raise CLICommandError(
                {
                    "command": command_list,
                    "exit_code": 2,
                    "error": str(exc),
                },
                exit_code=2,
            ) from exc

    payload = {
        "command": command_list,
        "exit_code": 0,
        "result": reduced,
    }
    if input_items is not None:
        payload["input_items"] = input_items
    if isinstance(reduced, list):
        payload["returned_items"] = len(reduced)
    if stderr_preview:
        payload["stderr"] = stderr_preview
    return payload


def inspect_json_command(
    *,
    command: Sequence[str],
    sample_items: int = 100,
    manifest_dir: Path | None = None,
) -> dict[str, Any]:
    if not command:
        raise ValueError("A wrapped command is required.")
    if sample_items < 1:
        raise ValueError("--sample-items must be greater than 0.")

    command_list, data, stderr_preview = _load_json_command_output(command)
    manifest = _build_manifest(command_list, data, sample_items)
    target_dir = manifest_dir or Path(".fieldflow") / "inspect"
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = target_dir / f"{manifest['command_hash']}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    payload = dict(manifest)
    payload["manifest_path"] = str(manifest_path)
    if stderr_preview:
        payload["stderr"] = stderr_preview
    return payload


def _load_json_command_output(
    command: Sequence[str],
) -> tuple[list[str], Any, str | None]:
    command_list = list(command)
    try:
        completed = subprocess.run(
            command_list,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise CLICommandError(
            {
                "command": command_list,
                "error": f"Command not found: {command_list[0]}",
            },
            exit_code=127,
        ) from exc

    stderr_preview = _trim_text(completed.stderr)

    if completed.returncode != 0:
        payload: dict[str, Any] = {
            "command": command_list,
            "exit_code": completed.returncode,
            "error": "Wrapped command exited with a non-zero status.",
        }
        if stderr_preview:
            payload["stderr"] = stderr_preview
        raise CLICommandError(payload, exit_code=completed.returncode)

    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        payload = {
            "command": command_list,
            "exit_code": 2,
            "error": "Wrapped command did not emit valid JSON on stdout.",
        }
        if stderr_preview:
            payload["stderr"] = stderr_preview
        raise CLICommandError(payload, exit_code=2) from exc

    return command_list, data, stderr_preview


def _build_manifest(command: list[str], data: Any, sample_items: int) -> dict[str, Any]:
    root_type = _json_type_name(data)
    manifest: dict[str, Any] = {
        "manifest_version": 1,
        "command": command,
        "command_hash": _command_hash(command),
        "root_type": root_type,
        "paths": [],
        "path_count": 0,
    }

    if isinstance(data, list):
        sampled = data[:sample_items]
        manifest["input_items"] = len(data)
        manifest["sampled_items"] = len(sampled)
        path_entries = _inspect_list_samples(sampled)
    elif isinstance(data, dict):
        manifest["sampled_items"] = 1
        path_entries = _inspect_object_sample(data)
    else:
        manifest["sampled_items"] = 1
        path_entries = [{"path": "", "types": [root_type]}]

    manifest["paths"] = path_entries
    manifest["path_count"] = len(path_entries)
    return manifest


def _inspect_list_samples(samples: list[Any]) -> list[dict[str, Any]]:
    if not samples:
        return []

    path_types: dict[str, set[str]] = {}
    for sample in samples:
        seen = _collect_sample_paths(sample, prefix="[]")
        for path, types in seen.items():
            collected = path_types.setdefault(path, set())
            collected.update(types)

    entries = []
    for path in sorted(path_types):
        entries.append(
            {
                "path": path,
                "types": sorted(path_types[path]),
            }
        )
    return entries


def _inspect_object_sample(sample: dict[str, Any]) -> list[dict[str, Any]]:
    seen = _collect_sample_paths(sample)
    entries = []
    for path in sorted(seen):
        entries.append(
            {
                "path": path,
                "types": sorted(seen[path]),
            }
        )
    return entries


def _collect_sample_paths(value: Any, *, prefix: str = "") -> dict[str, set[str]]:
    seen: dict[str, set[str]] = {}
    _visit_value(value, prefix, seen)
    return seen


def _visit_value(value: Any, prefix: str, seen: dict[str, set[str]]) -> None:
    if prefix:
        seen.setdefault(prefix, set()).add(_json_type_name(value))

    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = key if not prefix else f"{prefix}.{key}"
            _visit_value(child, child_prefix, seen)
        return

    if isinstance(value, list):
        child_prefix = "[]" if not prefix else f"{prefix}[]"
        for child in value:
            _visit_value(child, child_prefix, seen)


def _command_hash(command: list[str]) -> str:
    digest = hashlib.sha256(
        json.dumps(command, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    return digest[:16]


def _json_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "list"
    return "unknown"


def _limit_items(data: Any, max_items: int | None) -> Any:
    if max_items is None or not isinstance(data, list):
        return data
    return data[:max_items]


def _trim_text(text: str, limit: int = 1000) -> str | None:
    cleaned = text.strip()
    if not cleaned:
        return None
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit]}..."
