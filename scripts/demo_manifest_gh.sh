#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/demo_manifest_gh.sh [options]

Run a repeatable GitHub CLI vs FieldFlow demo for issues and pull requests.

Options:
  --repo OWNER/REPO     GitHub repository to query (default: mnfst/manifest)
  --state STATE         GitHub state filter for issues and PRs (default: open)
  --limit N             Max issues / PRs to fetch per command (default: 50)
  --output-dir DIR      Directory for saved demo artifacts (default: system temp dir)
  -h, --help            Show this help text

Requirements:
  - gh on PATH and authenticated
  - fieldflow-cli on PATH
  - python on PATH with tiktoken installed

This script compares full stdout payloads after minifying JSON on both sides.
FieldFlow numbers therefore include its own small wrapper metadata:
command, exit_code, result, input_items, returned_items.
EOF
}

log() {
  printf '==> %s\n' "$*"
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

require_command() {
  local name="$1"
  command -v "$name" >/dev/null 2>&1 || fail "missing required command: $name"
}

REPO="mnfst/manifest"
STATE="open"
LIMIT="50"
OUTPUT_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      [[ $# -ge 2 ]] || fail "--repo requires a value"
      REPO="$2"
      shift 2
      ;;
    --state)
      [[ $# -ge 2 ]] || fail "--state requires a value"
      STATE="$2"
      shift 2
      ;;
    --limit)
      [[ $# -ge 2 ]] || fail "--limit requires a value"
      LIMIT="$2"
      shift 2
      ;;
    --output-dir)
      [[ $# -ge 2 ]] || fail "--output-dir requires a value"
      OUTPUT_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      fail "unknown argument: $1"
      ;;
  esac
done

[[ "$LIMIT" =~ ^[1-9][0-9]*$ ]] || fail "--limit must be a positive integer"

require_command gh
require_command fieldflow-cli
require_command python

gh auth status >/dev/null 2>&1 || fail "gh is not authenticated; run 'gh auth login'"

python - <<'PY' >/dev/null 2>&1 || fail "python package 'tiktoken' is required for token counts"
import tiktoken
PY

if [[ -z "$OUTPUT_DIR" ]]; then
  safe_repo="${REPO//\//-}"
  OUTPUT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/fieldflow-demo-${safe_repo}-XXXXXX")"
else
  mkdir -p "$OUTPUT_DIR"
fi

OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
log "writing demo artifacts to $OUTPUT_DIR"

issue_json_fields="number,title,state,labels,author,comments,updatedAt,url"
pr_json_fields="number,title,state,labels,author,reviews,reviewDecision,updatedAt,url"

issue_raw_cmd=(
  gh issue list
  --repo "$REPO"
  --state "$STATE"
  --limit "$LIMIT"
  --json "$issue_json_fields"
)

pr_raw_cmd=(
  gh pr list
  --repo "$REPO"
  --state "$STATE"
  --limit "$LIMIT"
  --json "$pr_json_fields"
)

cd "$OUTPUT_DIR"

log "capturing raw issue payload"
"${issue_raw_cmd[@]}" > issues.raw.json

log "inspecting issue fields with FieldFlow"
fieldflow-cli inspect --sample-items "$LIMIT" -- "${issue_raw_cmd[@]}" > issues.inspect.json

log "capturing reduced issue payload"
fieldflow-cli \
  --field "[].number" \
  --field "[].title" \
  --field "[].state" \
  --field "[].updatedAt" \
  --field "[].url" \
  --field "[].author.login" \
  --field "[].labels[].name" \
  --field "[].comments[].author.login" \
  --field "[].comments[].createdAt" \
  -- \
  "${issue_raw_cmd[@]}" > issues.fieldflow.json

log "capturing raw PR payload"
"${pr_raw_cmd[@]}" > prs.raw.json

log "inspecting PR fields with FieldFlow"
fieldflow-cli inspect --sample-items "$LIMIT" -- "${pr_raw_cmd[@]}" > prs.inspect.json

log "capturing reduced PR payload"
fieldflow-cli \
  --field "[].number" \
  --field "[].title" \
  --field "[].state" \
  --field "[].updatedAt" \
  --field "[].url" \
  --field "[].author.login" \
  --field "[].labels[].name" \
  --field "[].reviewDecision" \
  --field "[].reviews[].author.login" \
  --field "[].reviews[].state" \
  --field "[].reviews[].submittedAt" \
  -- \
  "${pr_raw_cmd[@]}" > prs.fieldflow.json

cat > summary_prompt.txt <<'EOF'
Summarize the current open work in the repository.

Return:
- 5 issue themes with representative issue numbers
- PRs that appear to need review attention
- the most recently active work
- anything labeled high priority

Use only the provided JSON.
If comment or review bodies are not present, do not speculate about their content.
EOF

python - "$OUTPUT_DIR" "$REPO" "$STATE" "$LIMIT" <<'PY'
import json
from pathlib import Path
import sys

import tiktoken

output_dir = Path(sys.argv[1])
repo = sys.argv[2]
state = sys.argv[3]
limit = int(sys.argv[4])

enc = tiktoken.get_encoding("o200k_base")

files = {
    "issues.raw": output_dir / "issues.raw.json",
    "issues.fieldflow": output_dir / "issues.fieldflow.json",
    "prs.raw": output_dir / "prs.raw.json",
    "prs.fieldflow": output_dir / "prs.fieldflow.json",
}


def minified_json(text: str) -> str:
    return json.dumps(json.loads(text), separators=(",", ":"))


def stats_for(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    mini = minified_json(text)
    if isinstance(data, list):
        items = len(data)
    else:
        items = int(data.get("returned_items", 0))
    return {
        "items": items,
        "bytes_minified": len(mini.encode("utf-8")),
        "tokens_minified_o200k": len(enc.encode(mini)),
    }


stats = {name: stats_for(path) for name, path in files.items()}
combined_raw_tokens = (
    stats["issues.raw"]["tokens_minified_o200k"]
    + stats["prs.raw"]["tokens_minified_o200k"]
)
combined_fieldflow_tokens = (
    stats["issues.fieldflow"]["tokens_minified_o200k"]
    + stats["prs.fieldflow"]["tokens_minified_o200k"]
)
reduction = 0.0
if combined_raw_tokens:
    reduction = 100 * (combined_raw_tokens - combined_fieldflow_tokens) / combined_raw_tokens

issue_manifest = json.loads((output_dir / "issues.inspect.json").read_text(encoding="utf-8"))
pr_manifest = json.loads((output_dir / "prs.inspect.json").read_text(encoding="utf-8"))

comparison = {
    "repo": repo,
    "state": state,
    "limit": limit,
    "metric": "minified JSON token count using tiktoken o200k_base",
    "note": "FieldFlow counts include its wrapper metadata as printed on stdout.",
    "stats": stats,
    "combined": {
        "raw_tokens_minified_o200k": combined_raw_tokens,
        "fieldflow_tokens_minified_o200k": combined_fieldflow_tokens,
        "token_reduction_percent": round(reduction, 1),
    },
    "inspect_manifests": {
        "issues": {
            "path_count": issue_manifest["path_count"],
            "manifest_path": issue_manifest["manifest_path"],
        },
        "prs": {
            "path_count": pr_manifest["path_count"],
            "manifest_path": pr_manifest["manifest_path"],
        },
    },
}

(output_dir / "comparison.json").write_text(
    json.dumps(comparison, indent=2) + "\n",
    encoding="utf-8",
)

print()
print(f"Demo artifacts: {output_dir}")
print(f"Repo: {repo}")
print(f"State: {state}")
print(f"Limit: {limit}")
print()
print(f"{'dataset':18} {'items':>5} {'bytes':>10} {'tokens':>10}")
for name in ("issues.raw", "issues.fieldflow", "prs.raw", "prs.fieldflow"):
    entry = stats[name]
    print(
        f"{name:18} "
        f"{entry['items']:>5} "
        f"{entry['bytes_minified']:>10} "
        f"{entry['tokens_minified_o200k']:>10}"
    )
print()
print(f"combined raw tokens:       {combined_raw_tokens}")
print(f"combined fieldflow tokens: {combined_fieldflow_tokens}")
print(f"token reduction:           {reduction:.1f}%")
print()
print("Saved files:")
for filename in (
    "issues.raw.json",
    "issues.inspect.json",
    "issues.fieldflow.json",
    "prs.raw.json",
    "prs.inspect.json",
    "prs.fieldflow.json",
    "comparison.json",
    "summary_prompt.txt",
):
    print(f"- {output_dir / filename}")
PY
