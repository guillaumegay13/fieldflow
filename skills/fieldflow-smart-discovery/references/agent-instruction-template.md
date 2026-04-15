# FieldFlow Discovery Instruction Template

Use this behavior whenever a FieldFlow tool request contains fuzzy intent.

1. Call `<tool>__discover_fields` with normal operation params.
2. Select `fields` only from returned `candidates`.
3. Call `<tool>` with both `fields` and `discovery_id`.
4. If `discovery_id` is invalid/expired, rerun discovery and retry once.

Selection policy:
- Prefer recall over misses.
- Include identifiers and status fields for context.
- Never invent selectors.
