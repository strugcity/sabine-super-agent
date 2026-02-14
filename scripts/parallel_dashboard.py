#!/usr/bin/env python3
"""
Parallel Session Dashboard Server
===================================

Serves a live-updating web dashboard for parallel Claude Code sessions.
Zero tokens burned — runs locally, reads .parallel/ JSON files directly.

Usage:
    python scripts/parallel_dashboard.py                    # all workspaces
    python scripts/parallel_dashboard.py --workspace adrs   # specific workspace
    python scripts/parallel_dashboard.py --port 3847        # custom port

Opens http://localhost:3847 in your browser automatically.
"""

import argparse
import http.server
import json
import logging
import os
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.parallel.models import SessionState

logger = logging.getLogger(__name__)

PARALLEL_ROOT = PROJECT_ROOT / ".parallel"
DEFAULT_PORT = 3847
HEARTBEAT_TIMEOUT = 300  # 5 minutes


def scan_workspaces(filter_workspace: Optional[str] = None) -> Dict[str, Any]:
    """Scan .parallel/ and return all workspace/session data."""
    result: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "workspaces": {},
    }

    if not PARALLEL_ROOT.exists():
        return result

    for ws_dir in sorted(PARALLEL_ROOT.iterdir()):
        if not ws_dir.is_dir() or ws_dir.name.startswith("."):
            continue
        if filter_workspace and ws_dir.name != filter_workspace:
            continue

        sessions: List[Dict[str, Any]] = []
        for sess_dir in sorted(ws_dir.iterdir()):
            if not sess_dir.is_dir() or sess_dir.name.startswith("."):
                continue

            status_file = sess_dir / "status.json"
            if not status_file.exists():
                sessions.append({
                    "session_id": sess_dir.name,
                    "state": "pending",
                    "message": "No status file yet",
                    "progress_pct": 0,
                })
                continue

            try:
                data = json.loads(status_file.read_text(encoding="utf-8"))
                # Check staleness for running sessions
                if data.get("state") == "running" and data.get("last_heartbeat"):
                    last_hb = datetime.fromisoformat(data["last_heartbeat"])
                    now = datetime.now(timezone.utc)
                    if (now - last_hb).total_seconds() > HEARTBEAT_TIMEOUT:
                        data["state"] = "timed_out"
                        data["message"] = (
                            f"No heartbeat for {HEARTBEAT_TIMEOUT}s "
                            f"(last: {data['last_heartbeat']})"
                        )

                # Check for completion markers
                data["has_completed_marker"] = (sess_dir / "COMPLETED").exists()
                data["has_failed_marker"] = (sess_dir / "FAILED").exists()

                sessions.append(data)
            except (json.JSONDecodeError, Exception) as e:
                sessions.append({
                    "session_id": sess_dir.name,
                    "state": "failed",
                    "message": f"Error reading status: {e}",
                    "progress_pct": 0,
                })

        counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0, "timed_out": 0}
        for s in sessions:
            state = s.get("state", "pending")
            if state in counts:
                counts[state] += 1

        result["workspaces"][ws_dir.name] = {
            "sessions": sessions,
            "counts": counts,
            "total": len(sessions),
        }

    return result


def read_session_log(workspace: str, session_id: str, tail: int = 50) -> List[Dict]:
    """Read a session's log.jsonl."""
    log_file = PARALLEL_ROOT / workspace / session_id / "log.jsonl"
    if not log_file.exists():
        return []
    try:
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        entries = [json.loads(line) for line in lines if line.strip()]
        return entries[-tail:]
    except Exception:
        return []


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Parallel Sessions Dashboard</title>
<style>
  :root {
    --bg: #0d1117;
    --surface: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --text-muted: #8b949e;
    --green: #3fb950;
    --red: #f85149;
    --yellow: #d29922;
    --blue: #58a6ff;
    --purple: #bc8cff;
    --orange: #f0883e;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', monospace;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding: 24px;
  }
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border);
  }
  .header h1 {
    font-size: 18px;
    font-weight: 600;
    letter-spacing: -0.02em;
  }
  .header-right {
    display: flex;
    align-items: center;
    gap: 16px;
    font-size: 12px;
    color: var(--text-muted);
  }
  .pulse {
    width: 8px; height: 8px;
    background: var(--green);
    border-radius: 50%;
    animation: pulse 2s ease-in-out infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }
  .summary-bar {
    display: flex;
    gap: 24px;
    margin-bottom: 24px;
    font-size: 13px;
  }
  .summary-item {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .dot {
    width: 10px; height: 10px;
    border-radius: 50%;
    display: inline-block;
  }
  .dot-running { background: var(--blue); }
  .dot-completed { background: var(--green); }
  .dot-failed { background: var(--red); }
  .dot-pending { background: var(--text-muted); }
  .dot-timed_out { background: var(--orange); }
  .workspace {
    margin-bottom: 32px;
  }
  .workspace-header {
    font-size: 14px;
    font-weight: 600;
    color: var(--purple);
    margin-bottom: 12px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .session-grid {
    display: grid;
    gap: 12px;
  }
  .session-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    cursor: pointer;
    transition: border-color 0.15s;
  }
  .session-card:hover {
    border-color: var(--blue);
  }
  .session-card.state-completed { border-left: 3px solid var(--green); }
  .session-card.state-failed { border-left: 3px solid var(--red); }
  .session-card.state-running { border-left: 3px solid var(--blue); }
  .session-card.state-timed_out { border-left: 3px solid var(--orange); }
  .session-card.state-pending { border-left: 3px solid var(--text-muted); }
  .session-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }
  .session-id {
    font-weight: 600;
    font-size: 14px;
  }
  .state-badge {
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .state-badge.running { background: rgba(88,166,255,0.15); color: var(--blue); }
  .state-badge.completed { background: rgba(63,185,80,0.15); color: var(--green); }
  .state-badge.failed { background: rgba(248,81,73,0.15); color: var(--red); }
  .state-badge.pending { background: rgba(139,148,158,0.15); color: var(--text-muted); }
  .state-badge.timed_out { background: rgba(240,136,62,0.15); color: var(--orange); }
  .task-desc {
    font-size: 12px;
    color: var(--text-muted);
    margin-bottom: 10px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .progress-container {
    margin-bottom: 8px;
  }
  .progress-track {
    width: 100%;
    height: 6px;
    background: var(--border);
    border-radius: 3px;
    overflow: hidden;
  }
  .progress-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.5s ease;
  }
  .progress-fill.running { background: var(--blue); }
  .progress-fill.completed { background: var(--green); }
  .progress-fill.failed { background: var(--red); }
  .progress-fill.pending { background: var(--text-muted); }
  .progress-fill.timed_out { background: var(--orange); }
  .progress-label {
    display: flex;
    justify-content: space-between;
    font-size: 11px;
    color: var(--text-muted);
    margin-top: 4px;
  }
  .message {
    font-size: 12px;
    color: var(--text);
    margin-top: 6px;
  }
  .errors {
    margin-top: 8px;
    padding: 8px;
    background: rgba(248,81,73,0.08);
    border-radius: 4px;
    font-size: 11px;
    color: var(--red);
    max-height: 80px;
    overflow-y: auto;
  }
  .output-files {
    margin-top: 8px;
    font-size: 11px;
    color: var(--green);
  }
  .log-panel {
    display: none;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
  }
  .log-panel.open { display: block; }
  .log-entry {
    font-size: 11px;
    color: var(--text-muted);
    padding: 2px 0;
    display: flex;
    gap: 8px;
  }
  .log-entry .ts { color: var(--text-muted); min-width: 80px; }
  .log-entry .ev { color: var(--blue); min-width: 80px; }
  .log-entry .msg { color: var(--text); }
  .empty-state {
    text-align: center;
    padding: 80px 20px;
    color: var(--text-muted);
    font-size: 14px;
  }
  .empty-state .big { font-size: 48px; margin-bottom: 16px; }
  .poll-counter {
    font-size: 11px;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
  }
</style>
</head>
<body>

<div class="header">
  <h1>Parallel Sessions</h1>
  <div class="header-right">
    <div class="pulse" id="pulse"></div>
    <span class="poll-counter" id="poll-counter">Connecting...</span>
  </div>
</div>

<div class="summary-bar" id="summary-bar"></div>
<div id="content"></div>

<script>
const POLL_INTERVAL = 3000;
let pollCount = 0;
let expandedSessions = new Set();

async function fetchData() {
  try {
    const res = await fetch('/api/status');
    return await res.json();
  } catch (e) {
    return null;
  }
}

async function fetchLog(workspace, sessionId) {
  try {
    const res = await fetch(`/api/log?workspace=${workspace}&session=${sessionId}`);
    return await res.json();
  } catch (e) {
    return [];
  }
}

function renderSummary(data) {
  const bar = document.getElementById('summary-bar');
  let totals = { pending: 0, running: 0, completed: 0, failed: 0, timed_out: 0 };
  let total = 0;

  for (const ws of Object.values(data.workspaces)) {
    for (const [k, v] of Object.entries(ws.counts)) {
      if (totals[k] !== undefined) totals[k] += v;
    }
    total += ws.total;
  }

  bar.innerHTML = `
    <div class="summary-item"><span class="dot dot-running"></span> ${totals.running} running</div>
    <div class="summary-item"><span class="dot dot-completed"></span> ${totals.completed} completed</div>
    <div class="summary-item"><span class="dot dot-failed"></span> ${totals.failed} failed</div>
    <div class="summary-item"><span class="dot dot-timed_out"></span> ${totals.timed_out} timed out</div>
    <div class="summary-item"><span class="dot dot-pending"></span> ${totals.pending} pending</div>
    <div class="summary-item" style="color:var(--text-muted)">|</div>
    <div class="summary-item">${total} total</div>
  `;
}

function renderSession(session, workspace) {
  const state = session.state || 'pending';
  const pct = session.progress_pct || 0;
  const sid = session.session_id;
  const key = `${workspace}/${sid}`;
  const isExpanded = expandedSessions.has(key);

  let errorsHtml = '';
  if (session.errors && session.errors.length > 0) {
    errorsHtml = `<div class="errors">${session.errors.map(e =>
      `<div>${escHtml(e)}</div>`).join('')}</div>`;
  }

  let outputHtml = '';
  if (session.output_files && session.output_files.length > 0) {
    outputHtml = `<div class="output-files">Output: ${session.output_files.map(f =>
      escHtml(f)).join(', ')}</div>`;
  }

  return `
    <div class="session-card state-${state}" onclick="toggleLog('${key}', '${workspace}', '${sid}')">
      <div class="session-top">
        <span class="session-id">${escHtml(sid)}</span>
        <span class="state-badge ${state}">${state.replace('_', ' ')}</span>
      </div>
      <div class="task-desc">${escHtml(session.task_description || session.message || '')}</div>
      <div class="progress-container">
        <div class="progress-track">
          <div class="progress-fill ${state}" style="width: ${pct}%"></div>
        </div>
        <div class="progress-label">
          <span>${escHtml(session.message || '')}</span>
          <span>${pct}%</span>
        </div>
      </div>
      ${errorsHtml}
      ${outputHtml}
      <div class="log-panel ${isExpanded ? 'open' : ''}" id="log-${key.replace('/', '-')}">
        <div style="color:var(--text-muted);font-size:11px;margin-bottom:4px">Event Log:</div>
        <div id="log-entries-${key.replace('/', '-')}">Loading...</div>
      </div>
    </div>
  `;
}

async function toggleLog(key, workspace, sessionId) {
  if (expandedSessions.has(key)) {
    expandedSessions.delete(key);
  } else {
    expandedSessions.add(key);
    const entries = await fetchLog(workspace, sessionId);
    const container = document.getElementById(`log-entries-${key.replace('/', '-')}`);
    if (container && entries.length > 0) {
      container.innerHTML = entries.map(e => {
        const ts = (e.timestamp || '').substring(11, 19);
        const details = e.details ? JSON.stringify(e.details).substring(0, 60) : '';
        return `<div class="log-entry">
          <span class="ts">${ts}</span>
          <span class="ev">${e.event || ''}</span>
          <span class="msg">${e.progress_pct || 0}% ${details}</span>
        </div>`;
      }).join('');
    } else if (container) {
      container.innerHTML = '<div style="color:var(--text-muted)">No log entries</div>';
    }
  }
  render(lastData);
}

function escHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

let lastData = null;

function render(data) {
  lastData = data;
  const content = document.getElementById('content');

  if (!data || Object.keys(data.workspaces).length === 0) {
    content.innerHTML = `
      <div class="empty-state">
        <div class="big">~</div>
        <div>No parallel sessions detected</div>
        <div style="margin-top:8px;font-size:12px">
          Sessions write to .parallel/&lt;workspace&gt;/&lt;session-id&gt;/
        </div>
      </div>`;
    return;
  }

  renderSummary(data);

  let html = '';
  for (const [wsName, ws] of Object.entries(data.workspaces)) {
    html += `<div class="workspace">
      <div class="workspace-header">${escHtml(wsName)} (${ws.total})</div>
      <div class="session-grid">
        ${ws.sessions.map(s => renderSession(s, wsName)).join('')}
      </div>
    </div>`;
  }
  content.innerHTML = html;

  // Re-open expanded log panels
  for (const key of expandedSessions) {
    const panel = document.getElementById(`log-${key.replace('/', '-')}`);
    if (panel) panel.classList.add('open');
  }
}

async function poll() {
  const data = await fetchData();
  pollCount++;
  const counter = document.getElementById('poll-counter');
  const ts = new Date().toLocaleTimeString();
  counter.textContent = `Poll #${pollCount} at ${ts}`;

  if (data) {
    render(data);
    const pulse = document.getElementById('pulse');
    pulse.style.background = 'var(--green)';
  }
}

poll();
setInterval(poll, POLL_INTERVAL);
</script>
</body>
</html>"""


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler serving the dashboard and API endpoints."""

    filter_workspace: Optional[str] = None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self._serve_html()
        elif path == "/api/status":
            self._serve_status()
        elif path == "/api/log":
            ws = params.get("workspace", [None])[0]
            sid = params.get("session", [None])[0]
            self._serve_log(ws, sid)
        else:
            self.send_error(404)

    def _serve_html(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(DASHBOARD_HTML.encode("utf-8"))

    def _serve_status(self) -> None:
        data = scan_workspaces(self.__class__.filter_workspace)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _serve_log(self, workspace: Optional[str], session_id: Optional[str]) -> None:
        if not workspace or not session_id:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error": "workspace and session required"}')
            return
        entries = read_session_log(workspace, session_id)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(json.dumps(entries).encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default request logging to keep terminal clean."""
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Parallel session dashboard server")
    parser.add_argument("--port", "-p", type=int, default=DEFAULT_PORT)
    parser.add_argument("--workspace", "-w", help="Filter to specific workspace")
    parser.add_argument("--no-open", action="store_true", help="Don't auto-open browser")
    args = parser.parse_args()

    DashboardHandler.filter_workspace = args.workspace

    server = http.server.HTTPServer(("127.0.0.1", args.port), DashboardHandler)
    url = f"http://localhost:{args.port}"

    ws_msg = f" (workspace: {args.workspace})" if args.workspace else ""
    print(f"Dashboard running at {url}{ws_msg}")
    print("Press Ctrl+C to stop\n")

    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
        server.server_close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
