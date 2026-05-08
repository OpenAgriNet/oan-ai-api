# Training Log Event Schema (v1)

This schema is designed for downstream logs-to-training pipelines covering both Q&A and agentic behavior.

## Event Types

- `user`: user utterance content for a turn.
- `assistant`: assistant response content for a turn.
- `tool_call`: emitted when the assistant invokes a tool.
- `tool_result`: emitted when tool output is observed.
- `error`: emitted when request or execution fails.

## Core Fields

- `schema_version` (string): event schema version, currently `v1`.
- `timestamp` (ISO-8601 UTC string): event creation timestamp.
- `event_type` (enum): one of the types above.
- `session_id` (string): conversation/session identifier.
- `user_id` (string): user identifier from request.
- `source_lang` (string): source language code.
- `target_lang` (string): target language code.

## Optional Fields

- `content` (string): message text for `user`/`assistant`.
- `tool_name` (string): tool identifier for tool events.
- `tool_call_id` (string): call/result correlation id.
- `tool_args` (object): tool input payload.
- `tool_result` (any): tool output payload.
- `error_type` (string): Python error class name.
- `error_message` (string): error text.
- `metadata` (object): additional context, e.g. `content_id`.

## Validator Checks

`helpers/validate_training_events.py` enforces:

- tool call names exist in registered tools (`agents.tools.TOOLS`)
- every `tool_result` has a prior matching `tool_call_id`
- required ids on tool events are present

## Example

```json
{"schema_version":"v1","timestamp":"2026-05-08T13:12:00.000000+00:00","event_type":"tool_call","session_id":"abc","user_id":"u1","source_lang":"mr","target_lang":"mr","tool_name":"weather_forecast","tool_call_id":"call_42","tool_args":{"district":"Pune"},"metadata":{}}
```
