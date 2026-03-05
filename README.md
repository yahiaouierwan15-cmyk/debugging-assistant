# Debugging Assistant — MCP Server

## Overview

A debugging assistant that helps analyze log files through natural language.
Instead of reading thousands of lines manually, this MCP server lets an AI agent
ingest log files, search for patterns, detect anomalies, and correlate events
across multiple files.

Built with **FastMCP** (Python) as a school project for the *Building Agentic Systems with MCP* workshop.

## Setup

```bash
# Create and activate virtual environment
uv venv && source .venv/bin/activate

# Install MCP CLI (only dependency — re and json are stdlib)
uv pip install "mcp[cli]"
```

## Test with MCP Inspector

```bash
mcp dev server.py
```

## Claude Desktop / Gemini CLI Configuration

Add to your configuration file:

- **Claude Desktop:** `claude_desktop_config.json`
- **Gemini CLI:** `~/.gemini/settings.json`

```json
{
  "mcpServers": {
    "debugging-assistant": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["/absolute/path/to/server.py"]
    }
  }
}
```

> Replace `/absolute/path/to/` with the actual paths on your machine.

## Tools

### `ingest_log`

**Description:** Load a log file and auto-detect its format (JSONL, syslog, or plaintext).

| Parameter   | Type  | Required | Description                                        |
|-------------|-------|----------|----------------------------------------------------|
| `file_path` | `str` | yes      | Path to the log file                               |
| `format`    | `str` | no       | `"auto"`, `"jsonl"`, `"syslog"`, or `"plaintext"` |

**Example:**
> "Load the file sample.log" → calls `ingest_log(file_path="sample.log")`

---

### `search_logs`

**Description:** Search loaded logs by keyword, severity level, or time range.

| Parameter    | Type  | Required | Description                              |
|--------------|-------|----------|------------------------------------------|
| `query`      | `str` | no       | Text to search (case-insensitive)        |
| `level`      | `str` | no       | `ERROR`, `WARN`, `INFO`, or `DEBUG`      |
| `start_time` | `str` | no       | Start of range (YYYY-MM-DDTHH:MM:SS)    |
| `end_time`   | `str` | no       | End of range (YYYY-MM-DDTHH:MM:SS)      |

**Example:**
> "Show me all errors" → calls `search_logs(level="ERROR")`

---

### `get_error_summary`

**Description:** Group errors by message pattern and count occurrences.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)*  |      |          |             |

**Example:**
> "What are the most common errors?" → calls `get_error_summary()`

---

### `detect_anomalies`

**Description:** Find time windows with unusually high error rates.

| Parameter        | Type  | Required | Description                         |
|------------------|-------|----------|-------------------------------------|
| `window_minutes` | `int` | no       | Window size in minutes (default: 5) |

**Example:**
> "Were there any error spikes?" → calls `detect_anomalies(window_minutes=5)`

---

### `correlate_events`

**Description:** Find all entries within ±N seconds of a timestamp, across all files.

| Parameter        | Type  | Required | Description                               |
|------------------|-------|----------|-------------------------------------------|
| `timestamp`      | `str` | yes      | Reference time (YYYY-MM-DDTHH:MM:SS)     |
| `window_seconds` | `int` | no       | Seconds before/after to include (default: 30) |

**Example:**
> "What happened around 14:15:01?" → calls `correlate_events(timestamp="2025-01-15T14:15:01")`

## Resources

### `logs://files`

Lists all loaded log files with metadata: path, detected format, line count, and time range.

## Test Scenarios

### Scenario 1 — "What caused the error spike at 14:15?"

Expected tool sequence: `ingest_log` → `search_logs` → `correlate_events`

### Scenario 2 — "Are there patterns in the errors?"

Expected tool sequence: `ingest_log` → `detect_anomalies` → `get_error_summary`

### Scenario 3 — "Show me everything that happened around the DB timeout"

Expected tool sequence: `ingest_log` → `search_logs(query="timeout")` → `correlate_events`

## Limitations

- Log files are stored in memory — restarting the server clears all data.
- Syslog timestamps don't include the year, so cross-year comparison isn't possible.
- Very large files (>100k lines) may slow down search and anomaly detection.
- The server is read-only: it analyzes logs but cannot modify them.

## Comparison Results

*Tested on `sample.log` (25 entries, 2025-01-15T14:12:01 → 14:30:10) with the question:
"What caused the error spike around 14:15? Were there any anomalies?"*

| Dimension    | Without Tools                                                                 | With Tools                                                                                  |
|--------------|-------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| Accuracy     | Identified a DB issue around 14:15 but couldn't confirm exact timestamps or root cause | Exact first failure at 14:15:01 (line 8), confirmed 4x DB timeout + refused connection from 192.168.1.50 |
| Specificity  | Generic: "database connection errors in the 14:15 range, possibly network-related" | Precise: 4 distinct error patterns, 8 total errors, anomaly window 14:12→14:17 (7 errors/19 entries) |
| Completeness | Missed the secondary disk space issue at 14:25, missed the 2 retry warnings  | All 8 errors found, 9 events correlated around the incident, disk spike at 14:25 identified |
| Confidence   | Heavy hedging: "it seems", "possibly", "it appears the database may have…"    | Direct citations: exact line numbers, timestamps, normalized patterns (e.g. `<UUID>`, `<IP>`) |
| Latency      | 1 response, ~2–3 s                                                            | 4–5 tool calls (ingest → search → summary → anomalies → correlate), ~5–10 s total          |
