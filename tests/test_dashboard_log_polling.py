"""Execute the real dashboard polling code against delayed fake API replies."""

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_log_channels_ignore_late_success_failure_and_cleanup():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for dashboard behavior checks")
    source = (ROOT / "pages/dashboard/ui.js").read_text(encoding="utf-8")
    polling = source[
        source.index("let logsInFlight = null;") : source.index("function initTheme()")
    ]
    harness = r"""
const assert = require("node:assert/strict");
const state = { logs: [], logsLevel: "main", logsAfterSeq: 0, logsMax: 0, logsTimer: 0, logsSession: "" };
const pending = [];
const timers = new Map();
let timerId = 0;
const LOG_POLL_MS = 3000;
function apiGet(path, params) {
  assert.equal(path, "web/logs");
  return new Promise((resolve, reject) => pending.push({ params, resolve, reject }));
}
function markData() {}
function showAlert() { throw new Error("stale failure was shown"); }
function setInterval(fn) { timers.set(++timerId, fn); return timerId; }
function clearInterval(id) { timers.delete(id); }
const response = (level, seq, session = "session") => ({ level, session_id: session, next_seq: seq + 1, max_entries: 2, entries: [{ seq, level: level === "debug" ? "debug" : "info", lines: [level] }] });
const tick = () => new Promise(resolve => setImmediate(resolve));
"""
    scenarios = r"""
(async () => {
  const main = reloadLogs({ reset: true });
  const debug = setLogsLevel("debug");
  assert.equal(pending[1].params.level, "debug");
  pending[0].resolve(response("main", 90));
  assert.equal(await main, "skipped");
  assert.equal(logsResetPending, true);
  assert.deepEqual(state.logs, []);
  pending[1].resolve(response("debug", 2));
  await debug;
  assert.equal(state.logs[0].seq, 2);
  assert.equal(logsResetPending, false);

  const old = reloadLogs();
  const newMain = setLogsLevel("main");
  pending[2].reject(new Error("old network error"));
  assert.equal(await old, "skipped");
  assert.equal(logsResetPending, true);
  pending[3].resolve(response("main", 1));
  await newMain;
  assert.equal(state.logs.length, 1);
  assert.equal(state.logs[0].level, "info");

  const incremental = reloadLogs();
  assert.equal(pending[4].params.after_seq, 1);
  pending[4].resolve({ ...response("main", 2), entries: [response("main", 1).entries[0], response("main", 2).entries[0]] });
  await incremental;
  assert.deepEqual(state.logs.map(e => e.seq), [1, 2]);

  const restarted = reloadLogs();
  pending[5].resolve(response("main", 1, "new-session"));
  await tick();
  assert.equal(pending[6].params.after_seq, undefined);
  pending[6].resolve(response("main", 1, "new-session"));
  await restarted;
  assert.equal(state.logsSession, "new-session");
  assert.deepEqual(state.logs.map(e => e.seq), [1]);

  startLogPolling();
  const timer = state.logsTimer;
  timers.get(timer)();
  const changing = setLogsLevel("debug");
  pending[7].reject(new Error("old poll error"));
  await tick();
  assert.equal(logPollFailures, 0);
  pending[8].resolve(response("debug", 8, "new-session"));
  await changing;
  stopLogPolling();
  assert.equal(state.logsTimer, 0);
  startLogPolling();
  assert.notEqual(state.logsTimer, timer);
  stopLogPolling();
  console.log("log polling behavior passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        [node],
        input=harness + polling + scenarios,
        text=True,
        capture_output=True,
        timeout=15,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "log polling behavior passed" in result.stdout
