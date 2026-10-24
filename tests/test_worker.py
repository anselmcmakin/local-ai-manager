import json, time, threading, http.server
from conftest import load

class Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        n = int(self.headers["Content-Length"]); body = json.loads(self.rfile.read(n))
        Fake.last = body
        out = {"choices": [{"message": {"content": "OK:" + body["messages"][0]["content"][:5]}}],
               "usage": {"prompt_tokens": 10, "completion_tokens": 4}}
        b = json.dumps(out).encode(); self.send_response(200); self.end_headers(); self.wfile.write(b)

def server():
    s = http.server.HTTPServer(("127.0.0.1", 0), Fake); threading.Thread(target=s.serve_forever, daemon=True).start(); return s

def setup(home, monkeypatch, read=("~/LocalAI",)):
    s = server(); monkeypatch.setenv("LOCAL_AI_URL", f"http://127.0.0.1:{s.server_port}/v1/chat/completions")
    (home/"LocalAI"/"containment.json").write_text(json.dumps({"read_folders": list(read)}))
    w = load("worker"); w.ensure_dirs(); return w

def job(w, **kw):
    j = {"id": "j1", "model": "m", "instruction": "Sum"}; j.update(kw)
    (w.J/"inbox"/(j["id"] if isinstance(j["id"], str) and "/" not in j["id"] else "x")).with_suffix(".json").write_text(json.dumps(j))

def test_done_and_usage(home, monkeypatch):
    w = setup(home, monkeypatch); (home/"LocalAI"/"n.txt").write_text("hello")
    job(w, input_file="~/LocalAI/n.txt", temperature=0.7); w.process_once()
    r = json.loads((w.J/"done"/"j1.result.json").read_text())
    assert r["ok"] and r["output"].startswith("OK:")
    assert Fake.last["temperature"] == 0.7 and "hello" in Fake.last["messages"][0]["content"]
    u = json.loads((home/"LocalAI"/"usage.jsonl").read_text().splitlines()[0])
    assert u["prompt_tokens"] == 10 and u["completion_tokens"] == 4
    assert not list((w.J/"running").iterdir()) and not list((w.J/"inbox").iterdir())

def test_blocks_file_outside_allowlist(home, monkeypatch):
    w = setup(home, monkeypatch); (home/"secret.txt").write_text("x")
    job(w, input_file="~/secret.txt"); w.process_once()
    e = json.loads((w.J/"failed"/"j1.error.json").read_text())
    assert not e["ok"] and "read_folders" in e["error"]

def test_blocks_dotdot_escape(home, monkeypatch):
    w = setup(home, monkeypatch); (home/"secret.txt").write_text("x")
    job(w, input_file="~/LocalAI/../secret.txt"); w.process_once()
    assert (w.J/"failed"/"j1.error.json").exists()

def test_unsafe_id_cannot_escape(home, monkeypatch):
    w = setup(home, monkeypatch)
    job(w, id="../../evil"); w.process_once()
    assert not (home/"evil.result.json").exists()
    assert list((w.J/"done").glob("*.result.json"))

def test_missing_containment_fails_closed(home, monkeypatch):
    w = setup(home, monkeypatch); (home/"LocalAI"/"containment.json").unlink(); (home/"LocalAI"/"n.txt").write_text("a")
    job(w, input_file="~/LocalAI/n.txt"); w.process_once()
    assert (w.J/"failed"/"j1.error.json").exists()

def test_snooze_pauses_inbox_until_resumed(home, monkeypatch):
    w = setup(home, monkeypatch)
    (home/"LocalAI"/"watchdog_state.json").write_text(json.dumps({"snoozed_until": time.time() + 7200}))
    job(w); w.process_once()
    assert (w.J/"inbox"/"j1.json").exists() and not (w.J/"done"/"j1.result.json").exists()
    (home/"LocalAI"/"watchdog_state.json").write_text(json.dumps({"snoozed_until": 0}))
    w.process_once()
    assert (w.J/"done"/"j1.result.json").exists()
