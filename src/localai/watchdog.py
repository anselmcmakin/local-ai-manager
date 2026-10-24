# Local AI Manager watchdog v0.1.0. Run every 60 s by a scheduler.
import json, os, pathlib, shutil, socket, subprocess, time, urllib.request
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0   # no console flash under pythonw

R = pathlib.Path(os.path.expanduser("~/LocalAI"))
CFG = R / "watchdog.env.json"            # {"url": "...", "key": "..."}  user-only permissions
cfg = json.loads(CFG.read_text(encoding="utf-8-sig")) if CFG.exists() else {}
URL = os.environ.get("GROKBOT_WEBHOOK_URL", cfg.get("url"))
KEY = os.environ.get("GROKBOT_WEBHOOK_KEY", cfg.get("key"))
ENDPOINT = os.environ.get("LOCAL_AI_HEALTH", "http://127.0.0.1:11434/api/tags")
MODELS_DIR = os.path.expanduser(os.environ.get("MODELS_DIR", "~/.ollama"))
VRAM_LIMIT = float(os.environ.get("VRAM_LIMIT_PCT", 90))   # set from the user's 25/50/90 profile
TEMP_LIMIT = float(os.environ.get("GPU_TEMP_LIMIT", 85))
STATE = R / "watchdog_state.json"
SNOOZE_FILE = R / "snooze_until.txt"

def load_state():
    st = {"fails": 0, "hot": 0, "full": 0, "alerted": 0, "backoff": 0, "down": False, "snoozed_until": 0}
    if STATE.exists(): st.update(json.loads(STATE.read_text(encoding="utf-8-sig")))
    return st

def get_snooze_until(st):
    ts = float(st.get("snoozed_until") or st.get("snooze_until") or 0)
    if SNOOZE_FILE.exists():
        try: ts = max(ts, float(SNOOZE_FILE.read_text(encoding="utf-8-sig").strip() or 0))
        except Exception: pass
    return ts

def ok_endpoint():
    try: urllib.request.urlopen(ENDPOINT, timeout=5); return True
    except Exception: return False

def gpu():
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu,memory.used,memory.total",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW, timeout=10).stdout
        t, u, tot = [float(x) for x in o.splitlines()[0].split(",")]
        return t, 100 * u / tot
    except Exception:
        return None, None    # no NVIDIA GPU or Mac: temperature check skipped

def send(event):
    with open(R / "alerts.log", "a") as f: f.write(json.dumps(event) + "\n")
    if not URL: return
    h = {"Content-Type": "application/json"}
    if KEY: h["Authorization"] = f"Bearer {KEY}"   # PLACEHOLDER: use the header the routine panel shows
    try: urllib.request.urlopen(urllib.request.Request(URL, json.dumps(event).encode(), h), timeout=10)
    except Exception: pass


def main():
    st = load_state()
    now = time.time()
    su = get_snooze_until(st)
    if now < su:
        st.update(fails=0, hot=0, full=0, snooze_until=su, snoozed_until=su)
        STATE.write_text(json.dumps(st))
        return
    if su:
        st.update(snooze_until=0, snoozed_until=0)
        SNOOZE_FILE.unlink(missing_ok=True)
    up = ok_endpoint(); temp, vram = gpu()
    du = shutil.disk_usage(MODELS_DIR); free_pct = 100 * du.free / du.total; free_gb = du.free / 1e9
    st["fails"] = 0 if up else st["fails"] + 1
    st["hot"] = st["hot"] + 1 if temp is not None and temp >= TEMP_LIMIT else 0
    st["full"] = st["full"] + 1 if vram is not None and vram >= VRAM_LIMIT else 0
    problems = []
    if st["fails"] >= 3: problems.append("endpoint_down")
    if st["hot"] >= 3: problems.append(f"gpu_temp_{temp:.0f}C")
    if st["full"] >= 5: problems.append(f"vram_{vram:.0f}pct")
    if free_pct < 10 or free_gb < 20: problems.append(f"disk_{free_gb:.0f}GB_free")
    stuck = [p.name for p in (R / "jobs" / "running").glob("*.json") if time.time() - p.stat().st_mtime > 1800] if (R / "jobs" / "running").exists() else []
    if stuck: problems.append(f"stuck_jobs_{len(stuck)}")
    if problems and now - st["alerted"] >= st["backoff"]:
        send({"source": "local-ai-watchdog", "host": socket.gethostname(), "problems": problems,
              "temp_c": temp, "vram_pct": vram, "endpoint": ENDPOINT, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
        st["alerted"] = now
        st["backoff"] = 900 if st["backoff"] == 0 else min(st["backoff"] * 2, 3600)   # first alert now, then 15/30/60 min
        st["down"] = True
    elif not problems and st["down"]:
        send({"source": "local-ai-watchdog", "host": socket.gethostname(), "recovered": True, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
        st.update(down=False, backoff=0, alerted=0)
    STATE.write_text(json.dumps(st))

if __name__ == "__main__":
    main()
