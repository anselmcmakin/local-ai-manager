# ~/LocalAI/dashboard/dashboard.py  -  Local AI Manager dashboard (single file, no CDN, stdlib only; psutil optional)
import http.server, json, os, pathlib, platform, secrets, shutil, subprocess, threading, time, urllib.request
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0   # no console flash under pythonw

HOST, PORT = "127.0.0.1", 8765                      # loopback only. Never 0.0.0.0.
R = pathlib.Path(os.path.expanduser("~/LocalAI"))
TOKEN = secrets.token_urlsafe(16)                    # per-run token, required on every POST
EXTRA_HOSTS = [h for h in os.environ.get("LOCALAI_TS_HOST", "").split(",") if h]  # your tailnet name, only if using Tailscale Serve
RUNTIME = os.environ.get("LOCALAI_HEALTH", "http://127.0.0.1:11434/api/tags")
MODEL = os.environ.get("LOCALAI_MODEL", "")          # for Unload
OS = platform.system()
ACTIONS = {   # FIXED allowlist from the monitoring skill. The page never sends a command string.
  "Linux":   {"start": ["sudo", "-n", "systemctl", "start", "ollama"], "stop": ["sudo", "-n", "systemctl", "stop", "ollama"],
              "restart": ["sudo", "-n", "systemctl", "restart", "ollama"]},
  "Darwin":  {"start": ["open", "-a", "Ollama"], "stop": ["osascript", "-e", 'quit app "Ollama"'],
              "restart": ["sh", "-c", 'osascript -e \'quit app "Ollama"\'; sleep 3; open -a Ollama']},
  "Windows": {"start": ["schtasks", "/Run", "/TN", "LocalAI Ollama"], "stop": ["cmd", "/c", "schtasks /End /TN \"LocalAI Ollama\" & taskkill /IM ollama.exe /F"],
              "restart": ["cmd", "/c", "schtasks /End /TN \"LocalAI Ollama\" & taskkill /IM ollama.exe /F & timeout /t 3 /nobreak >nul & schtasks /Run /TN \"LocalAI Ollama\""]},
}.get(OS, {})
if MODEL: ACTIONS["unload"] = ["ollama", "stop", MODEL]
ACTIONS["pause_2h"] = "pause_2h"
ACTIONS["resume"] = "resume"
START = time.time(); HIST = []; LOCK = threading.Lock(); LAST = {}

def get(url, t=3):
    try: return json.loads(urllib.request.urlopen(url, timeout=t).read())
    except Exception: return None

def snooze_info():
    ts = 0.0
    for p, is_json in ((R / "watchdog_state.json", True), (R / "snooze_until.txt", False)):
        if p.exists():
            try:
                v = json.loads(p.read_text(encoding="utf-8-sig")) if is_json else p.read_text(encoding="utf-8-sig").strip()
                ts = max(ts, float((v.get("snoozed_until") or v.get("snooze_until") or 0) if is_json else (v or 0)))
            except Exception: pass
    rem = max(0, int(ts - time.time()))
    return (ts if rem > 0 else 0), rem

def do_snooze(pause):
    su = round(time.time() + 7200, 1) if pause else 0
    if pause:
        models = [x.get("name") for x in (get("http://127.0.0.1:11434/api/ps") or {}).get("models", []) if x.get("name")]
        if MODEL and MODEL not in models: models.append(MODEL)
        for m in models:
            try: urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:11434/api/generate", json.dumps({"model": m, "keep_alive": 0}).encode(), {"Content-Type": "application/json"}), timeout=5).read()
            except Exception: pass
            try: subprocess.run(["ollama", "stop", m], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW, timeout=15)
            except Exception: pass
    R.mkdir(parents=True, exist_ok=True)
    st = {"fails": 0, "hot": 0, "full": 0, "alerted": 0, "backoff": 0, "down": False, "snoozed_until": 0}
    sf = R / "watchdog_state.json"
    if sf.exists():
        try: st.update(json.loads(sf.read_text(encoding="utf-8-sig")))
        except Exception: pass
    st["snooze_until"] = st["snoozed_until"] = su
    if pause: st.update(fails=0, hot=0, full=0)
    sf.write_text(json.dumps(st), encoding="utf-8")
    tf = R / "snooze_until.txt"
    if pause: tf.write_text(str(su), encoding="utf-8")
    else: tf.unlink(missing_ok=True)
    return 0

def gpu():
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=name,temperature.gpu,memory.used,memory.total,power.draw,utilization.gpu",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW, timeout=5).stdout
        n, t, u, tot, p, ut = [x.strip() for x in o.splitlines()[0].split(",")]
        f = lambda v: float(v) if v.replace(".", "", 1).isdigit() else None
        return {"name": n, "temp_c": f(t), "vram_used_mb": f(u), "vram_total_mb": f(tot), "power_w": f(p), "util": f(ut)}
    except Exception:
        return None   # AMD (rocm-smi, fields unverified) and Mac (powermetrics needs sudo) show n/a

def ram():
    try:
        import psutil
        m = psutil.virtual_memory(); return {"used_gb": m.used / 1e9, "total_gb": m.total / 1e9, "cpu": psutil.cpu_percent()}
    except Exception:
        if os.name == "nt":   # Windows without psutil: GlobalMemoryStatusEx
            try:
                import ctypes
                class M(ctypes.Structure): _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(n, ctypes.c_ulonglong) for n in ("tot", "av", "tp", "ap", "tv", "av2", "ext")]
                m = M(); m.l = ctypes.sizeof(M); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
                return {"used_gb": (m.tot - m.av) / 1e9, "total_gb": m.tot / 1e9, "cpu": None}
            except Exception: return None
        try:
            d = dict(l.split(":")[0:2] for l in open("/proc/meminfo"))
            tot = int(d["MemTotal"].split()[0]) / 1e6; av = int(d["MemAvailable"].split()[0]) / 1e6
            return {"used_gb": tot - av, "total_gb": tot, "cpu": None}
        except Exception: return None

def tps():   # tokens/sec: llama-server /metrics if present, else last job in usage.jsonl (worker)
    try:
        for l in urllib.request.urlopen("http://127.0.0.1:8080/metrics", timeout=1).read().decode().splitlines():
            if l.startswith("llamacpp:predicted_tokens_seconds"): return float(l.split()[-1])
    except Exception: pass
    try:
        last = (R / "usage.jsonl").read_text(encoding="utf-8-sig").strip().splitlines()[-1]; return json.loads(last).get("tok_per_s")
    except Exception: return None

def jobs():
    out, counts = [], {}
    for s in ("running", "inbox", "done", "failed"):
        fs = sorted((R / "jobs" / s).glob("*.json"), key=os.path.getmtime, reverse=True) if (R / "jobs" / s).exists() else []
        counts[s] = len(fs)
        for f in fs[:8]:
            try: d = json.loads(f.read_text(encoding="utf-8-sig"))
            except Exception: d = {}
            out.append({"state": s, "id": d.get("id", f.stem), "age_s": int(time.time() - f.stat().st_mtime),
                        "snippet": str(d.get("output") or d.get("error") or d.get("instruction") or "")[:200]})
    out.sort(key=lambda j: j["age_s"]); return out[:12], counts

def alerts():
    try: return [json.loads(l) for l in (R / "alerts.log").read_text(encoding="utf-8-sig").splitlines()[-15:]][::-1]
    except Exception: return []

def sample():
    while True:
        up = get(RUNTIME) is not None
        g = gpu(); m = ram(); t = tps()
        try: du = shutil.disk_usage(os.path.expanduser(os.environ.get("MODELS_DIR", "~"))); disk = {"free_gb": du.free / 1e9, "total_gb": du.total / 1e9}
        except Exception: disk = None
        pt = {"t": int(time.time()), "temp": g and g["temp_c"], "vram": g and g["vram_total_mb"] and round(100 * g["vram_used_mb"] / g["vram_total_mb"], 1),
              "ram": m and round(100 * m["used_gb"] / m["total_gb"], 1), "tps": t, "up": up}
        with LOCK:
            HIST.append(pt); del HIST[:-720]           # 1 hour at 5 s
            if up and not LAST.get("up"): LAST["since"] = time.time()
            LAST.update(up=up, gpu=g, ram=m, disk=disk, tps=t)
        time.sleep(5)

def status():
    with LOCK: s = dict(LAST); h = list(HIST)
    j, c = jobs()
    su, rem = snooze_info()
    loaded = (get("http://127.0.0.1:11434/api/ps") or {}).get("models", [])
    acts = [a for a in ACTIONS if a != ("pause_2h" if rem > 0 else "resume")]
    return {"host": platform.node(), "os": OS, "up": s.get("up"), "up_for_s": int(time.time() - s["since"]) if s.get("up") and s.get("since") else 0,
            "dash_up_s": int(time.time() - START), "gpu": s.get("gpu"), "ram": s.get("ram"), "disk": s.get("disk"), "tps": s.get("tps"),
            "snoozed_until": su, "snooze_rem_s": rem,
            "loaded": [{"name": x.get("name"), "vram_gb": round((x.get("size_vram") or 0) / 1e9, 1), "ctx": x.get("context_length")} for x in loaded],
            "hist": h, "jobs": j, "counts": c, "alerts": alerts(), "actions": acts}

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _guard(self):   # block DNS rebinding / cross-site
        host = self.headers.get("Host", "").rsplit(":", 1)[0] if not self.headers.get("Host", "").startswith("[") else ""
        return host in ["127.0.0.1", "localhost"] + EXTRA_HOSTS
    def _send(self, code, body, ct):
        self.send_response(code); self.send_header("Content-Type", ct); self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY"); self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'")
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if not self._guard(): return self.send_error(403)
        if self.path == "/api/status": return self._send(200, json.dumps(status()).encode(), "application/json")
        if self.path in ("/", "/index.html"): return self._send(200, PAGE.replace("__TOKEN__", TOKEN).encode(), "text/html; charset=utf-8")
        self.send_error(404)
    def do_POST(self):
        a = self.path.rsplit("/", 1)[-1]
        origin = self.headers.get("Origin")
        if not self._guard() or self.headers.get("X-Token") != TOKEN or a not in ACTIONS or (origin and origin.split("//")[-1].rsplit(":", 1)[0] not in ["127.0.0.1", "localhost"] + EXTRA_HOSTS):
            return self.send_error(403)
        if ACTIONS[a] in ("pause_2h", "resume"):
            try: rc = do_snooze(a == "pause_2h")
            except Exception: rc = -1
        else:
            try: r = subprocess.run(ACTIONS[a], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW, timeout=60); rc = r.returncode
            except Exception: rc = -1
        R.mkdir(parents=True, exist_ok=True)
        with open(R / "dashboard_actions.log", "a", encoding="utf-8") as f: f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {a} rc={rc}\n")
        self._send(200, json.dumps({"action": a, "rc": rc}).encode(), "application/json")

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Local AI Manager</title><style>
:root{--bg:#0b0d12;--panel:#12151d;--panel2:#171b25;--line:#232838;--txt:#e7eaf2;--mut:#8a93a8;--acc:#7c9cff;--ok:#3ddc97;--warn:#ffb547;--bad:#ff5d6c;--r:16px}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(1200px 600px at 10% -10%,#1a2140 0,transparent 60%),var(--bg);color:var(--txt);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
header{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:20px 24px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:12px}.logo{width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,var(--acc),#b07cff);box-shadow:0 6px 24px #7c9cff55}
h1{font-size:18px;margin:0;font-weight:650;letter-spacing:.2px}.sub{color:var(--mut);font-size:12px}
.pills{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.pill{display:inline-flex;align-items:center;gap:8px;padding:6px 12px;border-radius:999px;background:var(--panel2);border:1px solid var(--line);font-weight:600}
.pill.snooze{border-color:#ffb54766;color:var(--warn);display:none}.pill.snooze.show{display:inline-flex}
.dot{width:9px;height:9px;border-radius:50%;background:var(--mut)}.up .dot{background:var(--ok);box-shadow:0 0 0 0 #3ddc9788;animation:p 2s infinite}.down .dot{background:var(--bad)}.snooze .dot{background:var(--warn)}
@keyframes p{70%{box-shadow:0 0 0 8px #3ddc9700}100%{box-shadow:0 0 0 0 #3ddc9700}}
main{padding:0 24px 32px;display:grid;gap:16px;grid-template-columns:repeat(12,1fr)}
.card{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:var(--r);padding:16px;min-width:0}
.c3{grid-column:span 3}.c4{grid-column:span 4}.c6{grid-column:span 6}.c8{grid-column:span 8}.c12{grid-column:span 12}
.k{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.8px}.v{font-size:28px;font-weight:700;margin-top:4px;font-variant-numeric:tabular-nums;transition:color .3s}
.gauges{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;text-align:center}.gauges canvas{width:100%;max-width:160px;aspect-ratio:1.4}
.chart{width:100%;height:170px}.row{display:flex;justify-content:space-between;align-items:center;gap:8px}
.btns{display:flex;gap:8px;flex-wrap:wrap}button{font:inherit;font-weight:600;border-radius:10px;border:1px solid var(--line);background:var(--panel2);color:var(--txt);padding:9px 14px;cursor:pointer;transition:.15s}
button:hover{border-color:var(--acc);transform:translateY(-1px)}button.danger{border-color:#ff5d6c55;color:#ffb3ba}button.warn{border-color:#ffb54766;color:var(--warn)}button.primary{background:var(--acc);border-color:var(--acc);color:#0b0d12}
table{width:100%;border-collapse:collapse}td{padding:8px 6px;border-top:1px solid var(--line);vertical-align:top}td.s{width:84px}
.tag{font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;background:#ffffff10}.done{color:var(--ok)}.failed{color:var(--bad)}.running{color:var(--acc)}.inbox{color:var(--warn)}
.snip{color:var(--mut);font-size:12px;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.alert{padding:8px 0;border-top:1px solid var(--line);font-size:13px}.alert b{color:var(--warn)}.empty{color:var(--mut);padding:10px 0}
.modal{position:fixed;inset:0;background:#05060acc;backdrop-filter:blur(6px);display:none;align-items:center;justify-content:center;padding:20px;z-index:9}
.modal.show{display:flex}.box{background:var(--panel2);border:1px solid var(--line);border-radius:18px;padding:22px;max-width:380px;width:100%;box-shadow:0 30px 80px #000a;animation:in .18s ease-out}
@keyframes in{from{transform:scale(.96);opacity:0}}.box h3{margin:0 0 8px}.box p{color:var(--mut);margin:0 0 18px}
.toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:var(--panel2);border:1px solid var(--line);padding:10px 16px;border-radius:12px;opacity:0;transition:.3s}.toast.show{opacity:1}
@media(max-width:1000px){.c3{grid-column:span 6}.c4,.c6,.c8{grid-column:span 12}}
@media(max-width:560px){main{padding:0 12px 24px;gap:12px}header{padding:16px 12px}.c3{grid-column:span 6}.v{font-size:22px}.btns button{flex:1}}
</style></head><body>
<header><div class="brand"><div class="logo"></div><div><h1>Local AI Manager</h1><div class="sub" id="host">connecting…</div></div></div>
<div class="pills"><div class="pill snooze" id="snz"><span class="dot"></span><span id="snztxt">Paused</span></div><div class="pill" id="state"><span class="dot"></span><span id="stxt">Checking</span></div></div></header>
<main>
<div class="card c3"><div class="k">Uptime</div><div class="v" id="uptime">–</div><div class="sub" id="model">–</div></div>
<div class="card c3"><div class="k">Tokens / sec</div><div class="v" id="tps">–</div><div class="sub">latest generation</div></div>
<div class="card c3"><div class="k">Jobs</div><div class="v" id="jobsn">–</div><div class="sub" id="jobsd">–</div></div>
<div class="card c3"><div class="k">Disk free</div><div class="v" id="disk">–</div><div class="sub" id="power">–</div></div>
<div class="card c4"><div class="row"><div class="k">Live</div><div class="sub" id="gname"></div></div>
<div class="gauges"><div><canvas id="gT"></canvas><div class="sub">GPU temp</div></div><div><canvas id="gV"></canvas><div class="sub">VRAM</div></div><div><canvas id="gR"></canvas><div class="sub">RAM</div></div></div></div>
<div class="card c8"><div class="row"><div class="k">Temperature · VRAM · RAM (last hour)</div><div class="sub"><span style="color:#ff8a5c">● temp °C</span> <span style="color:#7c9cff">● VRAM %</span> <span style="color:#3ddc97">● RAM %</span></div></div><canvas class="chart" id="c1"></canvas></div>
<div class="card c8"><div class="k">Tokens per second</div><canvas class="chart" id="c2"></canvas></div>
<div class="card c4"><div class="k">Controls</div><p class="sub">Every action asks to confirm and is logged on this machine.</p><div class="btns" id="btns"></div></div>
<div class="card c8"><div class="k">Handed-off jobs</div><table id="jobs"></table></div>
<div class="card c4"><div class="k">Alerts</div><div id="alerts"></div></div>
</main>
<div class="modal" id="m"><div class="box"><h3 id="mt"></h3><p id="mp"></p><div class="btns" style="justify-content:flex-end"><button id="mc">Cancel</button><button class="primary" id="mo">Confirm</button></div></div></div>
<div class="toast" id="toast"></div>
<script>
const $=id=>document.getElementById(id),TOKEN="__TOKEN__";
const fmt=s=>{if(!s)return"–";const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);return d?d+"d "+h+"h":h?h+"h "+m+"m":m+"m"};
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const col=(v,w,b)=>v==null?"#8a93a8":v>=b?"#ff5d6c":v>=w?"#ffb547":"#3ddc97";
const G={};function gauge(id,val,max,unit,w,b){const c=$(id),r=devicePixelRatio||1,W=c.clientWidth,H=c.clientHeight;c.width=W*r;c.height=H*r;const x=c.getContext("2d");x.scale(r,r);
 G[id]=G[id]??0;const tgt=val==null?0:Math.min(val/max,1);G[id]+=(tgt-G[id])*.35;const cx=W/2,cy=H*.78,rad=Math.min(W/2,H*.75)-8;
 x.lineCap="round";x.lineWidth=10;x.strokeStyle="#232838";x.beginPath();x.arc(cx,cy,rad,Math.PI,2*Math.PI);x.stroke();
 const g=x.createLinearGradient(0,0,W,0);g.addColorStop(0,"#7c9cff");g.addColorStop(1,col(val,w,b));x.strokeStyle=g;x.beginPath();x.arc(cx,cy,rad,Math.PI,Math.PI+Math.PI*G[id]);x.stroke();
 x.fillStyle="#e7eaf2";x.font="700 20px system-ui";x.textAlign="center";x.fillText(val==null?"n/a":Math.round(val)+unit,cx,cy-4)}
function chart(id,series,maxY){const c=$(id),r=devicePixelRatio||1,W=c.clientWidth,H=c.clientHeight;c.width=W*r;c.height=H*r;const x=c.getContext("2d");x.scale(r,r);
 const pad=28;x.strokeStyle="#232838";x.fillStyle="#8a93a8";x.font="11px system-ui";x.lineWidth=1;
 const all=series.flatMap(s=>s.d.filter(v=>v!=null)),top=maxY||Math.max(10,...all)*1.15;
 for(let i=0;i<=4;i++){const y=8+(H-pad)*(i/4);x.beginPath();x.moveTo(pad,y);x.lineTo(W,y);x.stroke();x.fillText(Math.round(top*(1-i/4)),2,y+4)}
 series.forEach(s=>{const n=s.d.length;if(n<2)return;x.beginPath();let st=false;s.d.forEach((v,i)=>{if(v==null){st=false;return}const X=pad+(W-pad)*i/(n-1),Y=8+(H-pad)*(1-v/top);st?x.lineTo(X,Y):x.moveTo(X,Y);st=true});
  x.strokeStyle=s.c;x.lineWidth=2;x.stroke();x.lineTo(W,H-pad+8);x.lineTo(pad,H-pad+8);x.closePath();const g=x.createLinearGradient(0,0,0,H);g.addColorStop(0,s.c+"33");g.addColorStop(1,s.c+"00");x.fillStyle=g;x.fill()})}
let S=null;
const LABEL={start:"Start runtime",stop:"Stop runtime",restart:"Restart runtime",unload:"Unload model",pause_2h:"Pause 2h (Game Mode)",resume:"Resume"};
const DESC={start:"Starts the local AI runtime on this computer.",pause_2h:"Unloads models from GPU VRAM and snoozes watchdog alerts and queued jobs for 2 hours.",resume:"Clears Game Mode snooze so queued jobs and watchdog alerts resume immediately."};
function ask(a){$("mt").textContent=(LABEL[a]||a)+"?";$("mp").textContent=DESC[a]||"Running jobs may be interrupted. This runs a fixed command on this computer.";
 $("m").classList.add("show");$("mo").onclick=async()=>{$("m").classList.remove("show");try{const r=await fetch("/action/"+a,{method:"POST",headers:{"X-Token":TOKEN}});const j=await r.json();toast(j.rc===0?(LABEL[a]||a)+": done":(LABEL[a]||a)+": failed (code "+j.rc+")");poll()}catch(e){toast("Request failed")}}}
$("mc").onclick=()=>$("m").classList.remove("show");$("m").onclick=e=>{if(e.target.id==="m")$("m").classList.remove("show")};
function toast(t){$("toast").textContent=t;$("toast").classList.add("show");setTimeout(()=>$("toast").classList.remove("show"),3000)}
function render(){if(!S)return;const g=S.gpu||{},m=S.ram||{},h=S.hist||[];
 $("host").textContent=S.host+" · "+S.os+" · 127.0.0.1 only";$("state").className="pill "+(S.up?"up":"down");$("stxt").textContent=S.up?"Online":"Offline";
 const snz=S.snooze_rem_s>0;$("snz").className="pill snooze"+(snz?" show":"");if(snz)$("snztxt").textContent="Game Mode · "+fmt(S.snooze_rem_s)+" left";
 $("uptime").textContent=S.up?fmt(S.up_for_s):"Offline";$("model").textContent=S.loaded.length?S.loaded.map(l=>l.name+" · "+l.vram_gb+" GB"+(l.ctx?" · "+Math.round(l.ctx/1000)+"K ctx":"")).join(", "):"no model loaded";
 $("tps").textContent=S.tps==null?"–":S.tps.toFixed(1);const c=S.counts||{};$("jobsn").textContent=(c.running||0)+" running";$("jobsd").textContent=(c.inbox||0)+" queued · "+(c.done||0)+" done · "+(c.failed||0)+" failed";
 $("disk").textContent=S.disk?Math.round(S.disk.free_gb)+" GB":"–";$("power").textContent=g.power_w!=null?"GPU "+Math.round(g.power_w)+" W · util "+Math.round(g.util)+"%":"GPU power n/a";$("gname").textContent=g.name||"GPU telemetry n/a";
 gauge("gT",g.temp_c,100,"°",80,85);gauge("gV",g.vram_total_mb?100*g.vram_used_mb/g.vram_total_mb:null,100,"%",80,90);gauge("gR",m.total_gb?100*m.used_gb/m.total_gb:null,100,"%",80,90);
 chart("c1",[{d:h.map(p=>p.temp),c:"#ff8a5c"},{d:h.map(p=>p.vram),c:"#7c9cff"},{d:h.map(p=>p.ram),c:"#3ddc97"}],100);chart("c2",[{d:h.map(p=>p.tps),c:"#b07cff"}]);
 $("jobs").innerHTML=S.jobs.length?S.jobs.map(j=>`<tr><td class="s"><span class="tag ${j.state}">${j.state}</span></td><td><b>${esc(j.id)}</b> <span class="sub">${fmt(j.age_s)} ago</span><div class="snip">${esc(j.snippet)}</div></td></tr>`).join(""):'<tr><td class="empty">No jobs yet.</td></tr>';
 $("alerts").innerHTML=S.alerts.length?S.alerts.map(a=>`<div class="alert">${a.recovered?'<b style="color:#3ddc97">Recovered</b>':"<b>"+esc((a.problems||[]).join(", "))+"</b>"}<div class="sub">${esc(a.time||"")}</div></div>`).join(""):'<div class="empty">All clear.</div>';
 const B=$("btns");if(!B.dataset.k||B.dataset.k!==S.actions.join()){B.dataset.k=S.actions.join();B.innerHTML=S.actions.map(a=>`<button class="${a==="start"||a==="resume"?"primary":a==="stop"?"danger":a==="pause_2h"?"warn":""}" data-a="${a}">${LABEL[a]||a}</button>`).join("");B.querySelectorAll("button").forEach(b=>b.onclick=()=>ask(b.dataset.a))}}
async function poll(){try{S=await (await fetch("/api/status",{cache:"no-store"})).json()}catch(e){$("stxt").textContent="Dashboard unreachable"}render()}
let f=0;(function anim(){if(S&&f++<12){render()}requestAnimationFrame(anim)})();
poll();setInterval(()=>{poll();f=0},5000);addEventListener("resize",render);
</script></body></html>"""

if __name__ == "__main__":
    threading.Thread(target=sample, daemon=True).start()
    http.server.ThreadingHTTPServer((HOST, PORT), H).serve_forever()
