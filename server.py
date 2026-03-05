"""
Debugging Assistant — MCP Server
Ingère des fichiers de logs, détecte les patterns d'erreurs,
corrèle les événements et identifie les anomalies temporelles.
"""

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP

# On importe les fonctions fournies par le helper (on ne les réécrit pas)
from log_parser_helper import (
    SYSLOG_PATTERN,
    TIMESTAMP_PATTERN,
    detect_format,
    normalize_message,
)

# ── Création du serveur MCP ────────────────────────────────────────────
mcp = FastMCP("debugging-assistant")

# ── Stockage en mémoire ───────────────────────────────────────────────
# Toutes les entrées de log parsées, partagées entre les tools
log_entries: list[dict] = []
# Métadonnées de chaque fichier ingéré
loaded_files: list[dict] = []


# ── Fonctions internes de parsing ──────────────────────────────────────

def _parse_timestamp(raw: str) -> str | None:
    """Extrait un timestamp ISO depuis une ligne de log.
    Retourne None si aucun timestamp n'est trouvé."""
    match = TIMESTAMP_PATTERN.match(raw)
    if match:
        return match.group(1).replace("T", " ")
    # Tentative syslog
    match = SYSLOG_PATTERN.match(raw)
    if match:
        return match.group(1)
    return None


def _parse_level(raw: str) -> str:
    """Détecte le niveau de log (ERROR, WARN, INFO, DEBUG).
    Retourne 'UNKNOWN' si non trouvé."""
    upper = raw.upper()
    for level in ["ERROR", "WARN", "WARNING", "INFO", "DEBUG"]:
        if level in upper:
            return "ERROR" if level == "ERROR" else (
                "WARN" if level in ("WARN", "WARNING") else level
            )
    return "UNKNOWN"


def _parse_line(raw: str, file_path: str, line_number: int, fmt: str) -> dict:
    """Parse une ligne de log en dictionnaire normalisé.
    Adapte le parsing selon le format détecté (jsonl, syslog, plaintext)."""
    entry = {
        "timestamp": None,
        "level": "UNKNOWN",
        "message": raw.strip(),
        "raw": raw.strip(),
        "file": os.path.basename(file_path),
        "line": line_number,
    }

    if fmt == "jsonl":
        try:
            data = json.loads(raw)
            entry["timestamp"] = data.get("timestamp")
            entry["level"] = data.get("level", "UNKNOWN").upper()
            entry["message"] = data.get("message", data.get("msg", raw.strip()))
            return entry
        except json.JSONDecodeError:
            pass

    if fmt == "syslog":
        match = SYSLOG_PATTERN.match(raw)
        if match:
            entry["timestamp"] = match.group(1)
            entry["message"] = match.group(4)
            entry["level"] = _parse_level(match.group(4))
            return entry

    # Format plaintext : timestamp + level + message
    entry["timestamp"] = _parse_timestamp(raw)
    entry["level"] = _parse_level(raw)

    # Extraire le message après le level
    level_pattern = re.compile(r"(ERROR|WARN|WARNING|INFO|DEBUG)\s+", re.IGNORECASE)
    match = level_pattern.search(raw)
    if match:
        entry["message"] = raw[match.end():].strip()

    return entry


def _to_datetime(ts: str | None) -> datetime | None:
    """Convertit un string timestamp en objet datetime.
    Supporte les formats ISO courants."""
    if not ts:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%b %d %H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return None


# ── Tools MCP ──────────────────────────────────────────────────────────

@mcp.tool()
def ingest_log(file_path: str, format: str = "auto") -> str:
    """Load a log file into the debugging assistant.
    Auto-detects the format (jsonl, syslog, or plaintext) unless specified.
    The file is parsed line by line and stored for analysis by other tools.

    Args:
        file_path: Absolute or relative path to the log file.
        format: Log format — 'auto', 'jsonl', 'syslog', or 'plaintext'.
    """
    if not os.path.isfile(file_path):
        return f"Error: file not found — {file_path}"

    try:
        with open(file_path, "r", errors="replace") as f:
            lines = f.readlines()
    except PermissionError:
        return f"Error: permission denied — {file_path}"

    if not lines:
        return f"Error: file is empty — {file_path}"

    # Détection automatique du format via le helper fourni
    fmt = format if format != "auto" else detect_format(lines)

    count_before = len(log_entries)
    for i, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        entry = _parse_line(line, file_path, i, fmt)
        log_entries.append(entry)
    count_added = len(log_entries) - count_before

    # Calcul de la plage temporelle du fichier
    timestamps = [
        _to_datetime(e["timestamp"])
        for e in log_entries[count_before:]
        if e["timestamp"]
    ]
    time_range = "unknown"
    if timestamps:
        ts_min = min(timestamps)
        ts_max = max(timestamps)
        time_range = f"{ts_min.isoformat()} → {ts_max.isoformat()}"

    # Enregistrer les métadonnées du fichier
    metadata = {
        "path": file_path,
        "format": fmt,
        "line_count": count_added,
        "time_range": time_range,
    }
    loaded_files.append(metadata)

    return (
        f"Loaded {count_added} entries from {os.path.basename(file_path)} "
        f"(format: {fmt}, time range: {time_range})"
    )


@mcp.tool()
def search_logs(
    query: str = "",
    level: str = "",
    start_time: str = "",
    end_time: str = "",
) -> str:
    """Search loaded logs by keyword, severity level, or time range.
    All filters are optional and can be combined.
    Returns matching log entries with their file and line number.

    Args:
        query: Text to search for in log messages (case-insensitive).
        level: Filter by severity — 'ERROR', 'WARN', 'INFO', or 'DEBUG'.
        start_time: Only entries after this time (format: YYYY-MM-DDTHH:MM:SS).
        end_time: Only entries before this time (format: YYYY-MM-DDTHH:MM:SS).
    """
    if not log_entries:
        return "No logs loaded. Use ingest_log first."

    results = []
    start_dt = _to_datetime(start_time.replace("T", " ")) if start_time else None
    end_dt = _to_datetime(end_time.replace("T", " ")) if end_time else None

    for entry in log_entries:
        # Filtre par mot-clé
        if query and query.lower() not in entry["message"].lower():
            continue
        # Filtre par niveau
        if level and entry["level"] != level.upper():
            continue
        # Filtre par plage temporelle
        if start_dt or end_dt:
            entry_dt = _to_datetime(entry["timestamp"])
            if entry_dt:
                if start_dt and entry_dt < start_dt:
                    continue
                if end_dt and entry_dt > end_dt:
                    continue
            else:
                continue
        results.append(entry)

    if not results:
        return "No entries matched your filters."

    # Formatage lisible des résultats (limité à 50 pour ne pas surcharger)
    output_lines = [f"Found {len(results)} matching entries:\n"]
    for entry in results[:50]:
        ts = entry["timestamp"] or "no-timestamp"
        output_lines.append(
            f"[{ts}] {entry['level']} — {entry['message']}  "
            f"({entry['file']}:{entry['line']})"
        )
    if len(results) > 50:
        output_lines.append(f"\n... and {len(results) - 50} more entries.")

    return "\n".join(output_lines)


@mcp.tool()
def get_error_summary() -> str:
    """Group all ERROR-level entries by normalized message pattern
    and count occurrences of each. Useful for identifying the most
    frequent errors at a glance without reading every line.
    """
    if not log_entries:
        return "No logs loaded. Use ingest_log first."

    # Utilise normalize_message du helper pour regrouper les erreurs similaires
    error_groups: dict[str, int] = defaultdict(int)
    for entry in log_entries:
        if entry["level"] == "ERROR":
            normalized = normalize_message(entry["message"])
            error_groups[normalized] += 1

    if not error_groups:
        return "No errors found in the loaded logs."

    # Tri par nombre d'occurrences décroissant
    sorted_groups = sorted(error_groups.items(), key=lambda x: x[1], reverse=True)

    output_lines = [f"Error summary — {len(sorted_groups)} distinct patterns:\n"]
    for pattern, count in sorted_groups:
        output_lines.append(f"  [{count}x] {pattern}")

    total = sum(error_groups.values())
    output_lines.append(f"\nTotal errors: {total}")

    return "\n".join(output_lines)


@mcp.tool()
def detect_anomalies(window_minutes: int = 5) -> str:
    """Divide the log timeline into windows and find windows with
    unusually high error rates (more than 2× the average).
    Helps identify when problems started and how long they lasted.

    Args:
        window_minutes: Size of each time window in minutes (default: 5).
    """
    if not log_entries:
        return "No logs loaded. Use ingest_log first."

    if window_minutes < 1:
        return "Error: window_minutes must be at least 1."

    # Récupérer toutes les entrées avec un timestamp valide
    timed_entries = []
    for entry in log_entries:
        dt = _to_datetime(entry["timestamp"])
        if dt:
            timed_entries.append((dt, entry))

    if not timed_entries:
        return "No timestamped entries found — cannot detect anomalies."

    timed_entries.sort(key=lambda x: x[0])
    start = timed_entries[0][0]
    end = timed_entries[-1][0]
    delta = timedelta(minutes=window_minutes)

    # Comptage des erreurs par fenêtre
    windows: list[dict] = []
    current = start
    while current <= end:
        window_end = current + delta
        errors = sum(
            1 for dt, e in timed_entries
            if current <= dt < window_end and e["level"] == "ERROR"
        )
        total = sum(
            1 for dt, _ in timed_entries
            if current <= dt < window_end
        )
        windows.append({
            "start": current.isoformat(),
            "end": window_end.isoformat(),
            "errors": errors,
            "total": total,
        })
        current = window_end

    # Calcul de la moyenne d'erreurs par fenêtre
    error_counts = [w["errors"] for w in windows]
    avg_errors = sum(error_counts) / len(error_counts) if error_counts else 0

    # Les fenêtres anormales sont celles avec > 2× la moyenne (et au moins 1 erreur)
    threshold = max(avg_errors * 2, 1)
    anomalies = [w for w in windows if w["errors"] >= threshold]

    if not anomalies:
        return (
            f"No anomalies detected across {len(windows)} windows "
            f"of {window_minutes} min (avg errors/window: {avg_errors:.1f})."
        )

    output_lines = [
        f"Anomaly detection — {window_minutes}-min windows, "
        f"threshold: >{threshold:.0f} errors (avg: {avg_errors:.1f}):\n"
    ]
    for w in anomalies:
        output_lines.append(
            f"  {w['start']} → {w['end']}  "
            f"| {w['errors']} errors / {w['total']} entries"
        )

    return "\n".join(output_lines)


@mcp.tool()
def correlate_events(timestamp: str, window_seconds: int = 30) -> str:
    """Find all log entries within ±N seconds of a given timestamp,
    across all loaded files. Useful for understanding what happened
    around a specific event (e.g., an error).

    Args:
        timestamp: Reference point (format: YYYY-MM-DDTHH:MM:SS).
        window_seconds: How many seconds before and after to include (default: 30).
    """
    if not log_entries:
        return "No logs loaded. Use ingest_log first."

    ref_dt = _to_datetime(timestamp.replace("T", " "))
    if not ref_dt:
        return (
            f"Error: could not parse timestamp '{timestamp}'. "
            f"Expected format: YYYY-MM-DDTHH:MM:SS"
        )

    if window_seconds < 1:
        return "Error: window_seconds must be at least 1."

    delta = timedelta(seconds=window_seconds)
    correlated = []

    for entry in log_entries:
        entry_dt = _to_datetime(entry["timestamp"])
        if entry_dt and abs((entry_dt - ref_dt).total_seconds()) <= window_seconds:
            correlated.append((entry_dt, entry))

    if not correlated:
        return (
            f"No entries found within ±{window_seconds}s of {timestamp}."
        )

    correlated.sort(key=lambda x: x[0])

    output_lines = [
        f"Found {len(correlated)} entries within ±{window_seconds}s "
        f"of {timestamp}:\n"
    ]
    for dt, entry in correlated:
        diff = (dt - ref_dt).total_seconds()
        sign = "+" if diff >= 0 else ""
        output_lines.append(
            f"  [{sign}{diff:.0f}s] {entry['level']} — {entry['message']}  "
            f"({entry['file']}:{entry['line']})"
        )

    return "\n".join(output_lines)


# ── Resource MCP ───────────────────────────────────────────────────────

@mcp.resource("logs://files")
def list_loaded_files() -> str:
    """List all loaded log files with metadata:
    path, detected format, line count, and time range."""
    if not loaded_files:
        return json.dumps({"files": [], "message": "No files loaded yet."})
    return json.dumps({"files": loaded_files}, indent=2)


# ── Point d'entrée ────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
