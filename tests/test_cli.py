from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from fieldflow.cli import main, run_cli_main

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_run_cli_filters_json_output_without_persisting_raw(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = [
        {
            "timestamp": "2026-04-16T09:00:00Z",
            "severity": "ERROR",
            "httpRequest": {"requestUrl": "https://api.example.com/programs"},
            "jsonPayload": {"message": "Primary failure", "detail": "stack trace"},
        },
        {
            "timestamp": "2026-04-16T09:01:00Z",
            "severity": "INFO",
            "httpRequest": {"requestUrl": "https://api.example.com/health"},
            "jsonPayload": {"message": "ignored"},
        },
    ]
    code = f"import json; data = {payload!r}; print(json.dumps(data))"

    main(
        [
            "run-cli",
            "--field",
            "[].timestamp",
            "--field",
            "[].severity",
            "--field",
            "[].jsonPayload.message",
            "--max-items",
            "1",
            "--",
            sys.executable,
            "-c",
            code,
        ]
    )

    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert result["input_items"] == 2
    assert result["returned_items"] == 1
    assert result["result"] == [
        {
            "timestamp": "2026-04-16T09:00:00Z",
            "severity": "ERROR",
            "jsonPayload": {"message": "Primary failure"},
        }
    ]
    assert "raw_ref" not in result


def test_run_cli_returns_compact_error_for_non_json_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "run-cli",
                "--",
                sys.executable,
                "-c",
                "print('not json')",
            ]
        )

    assert exc_info.value.code == 2

    captured = capsys.readouterr()
    error = json.loads(captured.err)

    assert error["error"] == "Wrapped command did not emit valid JSON on stdout."
    assert "raw_ref" not in error


def test_fieldflow_cli_entrypoint_runs_without_subcommand(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = (
        "import json; print(json.dumps([{"
        "'severity':'ERROR','jsonPayload':{'message':'boom'}},"
        "{'severity':'INFO','jsonPayload':{'message':'ignore'}}]))"
    )

    run_cli_main(
        [
            "--field",
            "[].severity",
            "--field",
            "[].jsonPayload.message",
            "--max-items",
            "1",
            "--",
            sys.executable,
            "-c",
            code,
        ]
    )

    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert result["returned_items"] == 1
    assert result["result"] == [
        {"severity": "ERROR", "jsonPayload": {"message": "boom"}}
    ]


def test_fieldflow_cli_inspect_persists_manifest_in_dot_fieldflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    code = (
        "import json; print(json.dumps([{"
        "'timestamp':'2026-04-16T09:00:00Z',"
        "'severity':'ERROR',"
        "'httpRequest':{'status':500,'requestUrl':'https://example.com'},"
        "'jsonPayload':{'message':'boom'}},"
        "{'timestamp':'2026-04-16T09:01:00Z','severity':'INFO'}]))"
    )

    run_cli_main(
        [
            "inspect",
            "--sample-items",
            "2",
            "--",
            sys.executable,
            "-c",
            code,
        ]
    )

    captured = capsys.readouterr()
    manifest = json.loads(captured.out)

    assert manifest["root_type"] == "list"
    assert manifest["input_items"] == 2
    assert manifest["sampled_items"] == 2
    assert manifest["manifest_path"].startswith(".fieldflow/inspect/")

    manifest_path = tmp_path / manifest["manifest_path"]
    assert manifest_path.exists()

    stored_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert stored_manifest["command_hash"] == manifest["command_hash"]
    assert {entry["path"]: entry for entry in stored_manifest["paths"]}[
        "[].severity"
    ] == {
        "path": "[].severity",
        "types": ["string"],
    }
    assert {entry["path"]: entry for entry in stored_manifest["paths"]}[
        "[].httpRequest.status"
    ] == {
        "path": "[].httpRequest.status",
        "types": ["integer"],
    }


def test_fieldflow_cli_can_import_from_another_workdir(tmp_path: Path) -> None:
    script = """
import sys
from fieldflow.cli import run_cli_main

run_cli_main([
    "inspect",
    "--sample-items",
    "1",
    "--",
    sys.executable,
    "-c",
    "import json; print(json.dumps([{'severity':'ERROR'}]))",
])
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    manifest = json.loads(completed.stdout)
    assert manifest["manifest_path"].startswith(".fieldflow/inspect/")
    assert (tmp_path / manifest["manifest_path"]).exists()
