import json, time
from conftest import load

def run(home, monkeypatch, n, temp=None, vram=None, up=False):
    monkeypatch.setenv("MODELS_DIR", str(home)); monkeypatch.delenv("GROKBOT_WEBHOOK_URL", raising=False)
    w = load("watchdog")
    monkeypatch.setattr(w, "ok_endpoint", lambda: up)
    monkeypatch.setattr(w, "gpu", lambda: (temp, vram))
    monkeypatch.setattr(w, "URL", None)
    for _ in range(n): w.main()
    log = home/"LocalAI"/"alerts.log"
    return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else [], json.loads((home/"LocalAI"/"watchdog_state.json").read_text())

def test_down_alerts_after_three_then_backs_off(home, monkeypatch):
    a, st = run(home, monkeypatch, 2)
    assert a == []
    a, st = run(home, monkeypatch, 3)
    assert len(a) == 1 and "endpoint_down" in a[0]["problems"] and st["backoff"] == 900

def test_temp_needs_three_minutes(home, monkeypatch):
    a, _ = run(home, monkeypatch, 2, temp=90, vram=10, up=True)
    assert a == []
    a, _ = run(home, monkeypatch, 1, temp=90, vram=10, up=True)
    assert a and a[0]["problems"] == ["gpu_temp_90C"]

def test_recovery_ping(home, monkeypatch):
    run(home, monkeypatch, 3)
    a, st = run(home, monkeypatch, 1, up=True)
    assert a[-1].get("recovered") and st["down"] is False

def test_healthy_is_silent(home, monkeypatch):
    a, _ = run(home, monkeypatch, 5, temp=60, vram=30, up=True)
    assert a == []

def test_snooze_skips_alerts_until_expired(home, monkeypatch):
    su = round(time.time() + 7200, 1)
    (home/"LocalAI"/"snooze_until.txt").write_text(str(su))
    a, st = run(home, monkeypatch, 5, temp=95, vram=99, up=False)
    assert a == [] and st["snoozed_until"] == su and st["fails"] == 0
    (home/"LocalAI"/"snooze_until.txt").write_text("1")
    (home/"LocalAI"/"watchdog_state.json").write_text(json.dumps({"snoozed_until": 1}))
    a, st = run(home, monkeypatch, 3, temp=60, vram=30, up=False)
    assert len(a) == 1 and "endpoint_down" in a[0]["problems"] and st["snoozed_until"] == 0
