import json, threading, urllib.request, urllib.error, http.server
import pytest
from conftest import load

@pytest.fixture
def dash(home, monkeypatch):
    d = load("dashboard")
    d.ACTIONS.clear(); d.ACTIONS["restart"] = ["true"]; d.ACTIONS["pause_2h"] = "pause_2h"; d.ACTIONS["resume"] = "resume"
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), d.H); threading.Thread(target=s.serve_forever, daemon=True).start()
    yield d, s.server_port
    s.shutdown()

def req(port, path, method="GET", headers=None):
    r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, headers=headers or {}, data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(r, timeout=5) as x: return x.status, x.read()
    except urllib.error.HTTPError as e: return e.code, b""

def test_binds_loopback_only():
    import pathlib
    src = (pathlib.Path(__file__).parents[1] / "src/localai/dashboard.py").read_text()
    assert 'HOST, PORT = "127.0.0.1", 8765' in src and "0.0.0.0\"" not in src.replace("Never 0.0.0.0", "")

def test_page_self_contained(dash):
    d, p = dash; code, body = req(p, "/")
    assert code == 200 and b"http://" not in body.split(b"<script>")[1] and b"cdn" not in body.lower()

def test_status_json(dash):
    d, p = dash; code, body = req(p, "/api/status")
    s = json.loads(body); assert code == 200 and "jobs" in s and "actions" in s

def test_rejects_foreign_host(dash):
    d, p = dash; assert req(p, "/", headers={"Host": "evil.example"})[0] == 403

def test_post_needs_token(dash):
    d, p = dash; assert req(p, "/action/restart", "POST")[0] == 403

def test_post_rejects_cross_origin(dash):
    d, p = dash; assert req(p, "/action/restart", "POST", {"X-Token": d.TOKEN, "Origin": "https://evil.example"})[0] == 403

def test_post_only_allowlisted(dash):
    d, p = dash
    assert req(p, "/action/rm", "POST", {"X-Token": d.TOKEN})[0] == 403
    code, body = req(p, "/action/restart", "POST", {"X-Token": d.TOKEN})
    assert code == 200 and json.loads(body)["rc"] == 0

def test_job_snippet_escaped_client_side(dash):
    d, p = dash; body = req(p, "/")[1]
    assert b"esc(j.snippet)" in body and b"esc(j.id)" in body

def test_pause_2h_and_resume_actions(dash, home):
    d, p = dash
    s0 = json.loads(req(p, "/api/status")[1])
    assert "pause_2h" in s0["actions"] and s0["snooze_rem_s"] == 0
    code, body = req(p, "/action/pause_2h", "POST", {"X-Token": d.TOKEN})
    assert code == 200 and json.loads(body)["rc"] == 0
    s1 = json.loads(req(p, "/api/status")[1])
    assert s1["snooze_rem_s"] > 7000 and "resume" in s1["actions"] and "pause_2h" not in s1["actions"]
    st = json.loads((home/"LocalAI"/"watchdog_state.json").read_text())
    assert st["snoozed_until"] > 0
    code, body = req(p, "/action/resume", "POST", {"X-Token": d.TOKEN})
    assert code == 200 and json.loads(body)["rc"] == 0
    s2 = json.loads(req(p, "/api/status")[1])
    assert s2["snooze_rem_s"] == 0 and "pause_2h" in s2["actions"]
    log = (home/"LocalAI"/"dashboard_actions.log").read_text()
    assert "pause_2h rc=0" in log and "resume rc=0" in log
