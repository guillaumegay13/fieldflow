---
name: fieldflow-cli
description: Use FieldFlow to inspect and reduce noisy JSON CLI output before it reaches model context. Trigger for read-only external CLI tasks likely to return large structured output, especially logs, list, describe, get, read, query, search, metrics, or status commands from tools like gcloud, gh, kubectl, aws, or similar CLIs that can emit JSON. Prefer `fieldflow-cli inspect` first, then rerun with explicit `--field` selectors. Do not use for tiny local commands, text-only commands, or mutating commands unless explicitly asked.
---

# FieldFlow CLI

Use this skill to keep large JSON CLI output out of model context.

## Qualify The Command

Use `fieldflow-cli` only when all of these are true:

- The command is read-only.
- The command is external or service-facing, not a tiny local shell command.
- The command can emit JSON on stdout.
- The expected output is likely large enough that raw output would pollute context.

Do not use this skill for commands like `pwd`, `date`, `ls`, `git status`, `rg`, or any mutating command such as `deploy`, `apply`, `delete`, or `create`.

## Inspect First

Run `fieldflow-cli inspect` before choosing selectors unless you already have a manifest for the exact same wrapped command.

```bash
fieldflow-cli inspect --sample-items 100 -- <wrapped command>
```

The inspect step writes a compact field catalog under `.fieldflow/inspect/` and prints the manifest to stdout. Treat that manifest as the source of truth for valid selectors.

The manifest is deterministic and intentionally small:

- `path`
- `types`

It does not store raw command output.

## Pick Minimal Fields

Choose the smallest field set that answers the user’s question.

Prefer fields like:

- timestamps
- severity or status
- identifiers or names
- URLs
- concise message fields
- latency, count, or state fields

Avoid broad selectors such as `[]` or whole nested objects unless the task truly needs them.

## Run The Reduced Command

After choosing selectors, rerun the command through `fieldflow-cli`.

```bash
fieldflow-cli \
  --field "[].timestamp" \
  --field "[].severity" \
  --field "[].jsonPayload.message" \
  -- \
  <wrapped command>
```

If the result is too narrow, broaden the selectors and rerun the reduced call. Do not fall back to raw output unless the user explicitly asks for it.

## JSON Output Rules

Prefer the CLI’s native JSON mode:

- `gcloud`: `--format=json`
- `kubectl`: `-o json`
- `gh`: `--json ...`
- `aws`: JSON is already standard, or use `--output json` when needed

If the command cannot emit JSON, do not use this skill.

## Gcloud Example

For noisy Cloud Run request or error logs:

```bash
fieldflow-cli inspect --sample-items 100 -- \
  gcloud logging read \
    'resource.type="cloud_run_revision" AND resource.labels.service_name="program-api-service" AND severity>=ERROR' \
    --project=train-3328b \
    --freshness=24h \
    --limit=2000 \
    --format=json
```

Then reduce to the smallest useful fields, for example:

```bash
fieldflow-cli \
  --field "[].timestamp" \
  --field "[].severity" \
  --field "[].httpRequest.requestMethod" \
  --field "[].httpRequest.requestUrl" \
  --field "[].httpRequest.status" \
  --field "[].httpRequest.latency" \
  -- \
  gcloud logging read \
    'resource.type="cloud_run_revision" AND resource.labels.service_name="program-api-service" AND severity>=ERROR' \
    --project=train-3328b \
    --freshness=24h \
    --limit=2000 \
    --format=json
```
