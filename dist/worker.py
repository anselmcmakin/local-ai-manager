# Local AI Manager job runner v0.1.0
import json, os, pathlib, re, shutil, time, urllib.request
R = pathlib.Path(os.path.expanduser("~/LocalAI"))
J = R / "jobs"
API = os.environ.get("LOCAL_AI_URL", "http://127.0.0.1:11434/v1/chat/completions")

def is_snoozed():
    ts = 0.0
    for p, is_json in ((R / "watchdog_state.json", True), (R / "snooze_until.txt", False)):
        if p.exists():
            try:
                v = json.loads(p.read_text(encoding="utf-8-sig")) if is_json else p.read_text(encoding="utf-8-sig").strip()
                ts = max(ts, float((v.get("snoozed_until") or v.get("snooze_until") or 0) if is_json else (v or 0)))
            except Exception: pass
    return time.time() < ts

def allowed(path):
    cfg = json.loads((R/"containment.json").read_text(encoding="utf-8-sig"))
    p = pathlib.Path(os.path.expanduser(path)).resolve()
    return any(p.is_relative_to(pathlib.Path(os.path.expanduser(a)).resolve()) for a in cfg.get("read_folders", []))

def safe_id(v, fallback):
    v = str(v or fallback)
    return v if re.fullmatch(r"[A-Za-z0-9._-]{1,80}", v) and v not in (".", "..") else fallback

def ensure_dirs():
    for d in ("inbox", "running", "done", "failed"):
        (J/d).mkdir(parents=True, exist_ok=True)

def process_once():
    if is_snoozed(): return
    for f in sorted((J/"inbox").glob("*.json")):
        if is_snoozed(): break
        run = J/"running"/f.name
        shutil.move(f, run)
        job = {}
        try:
            job = json.loads(run.read_text(encoding="utf-8-sig"))
            job["id"] = safe_id(job.get("id"), f.stem)
            text = ""
            if job.get("input_file"):
                if not allowed(job["input_file"]):
                    raise PermissionError("input_file outside read_folders in containment.json")
                text = open(os.path.expanduser(job["input_file"]), encoding="utf-8-sig", errors="replace").read()
            prompt = (job["instruction"] + "\n\n" + text).strip()
            t0 = time.time()
            if "/api/" in API or ":11434" in API and not os.environ.get("LOCAL_AI_URL"):
                nurl = API.split("/v1/")[0].rstrip("/") + "/api/chat"
                opts = {"num_predict": job.get("max_tokens", 2048)}
                for k in ("temperature", "top_p", "num_ctx"):
                    if k in job: opts[k] = job[k]
                body = {"model": job["model"], "stream": False, "think": bool(job.get("think", False)),
                        "messages": [{"role": "user", "content": prompt}], "options": opts}
                out = json.loads(urllib.request.urlopen(urllib.request.Request(nurl, json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=600).read())
                secs = time.time() - t0
                content = (out.get("message") or {}).get("content") or ""
                usage = {"prompt_tokens": out.get("prompt_eval_count", 0), "completion_tokens": out.get("eval_count", 0)}
                ed = (out.get("eval_duration") or 0) / 1e9
                tps = round(usage["completion_tokens"] / ed, 1) if ed else (round(usage["completion_tokens"] / secs, 1) if secs else None)
            else:
                body = {"model": job["model"], "max_tokens": job.get("max_tokens", 2048), "reasoning_effort": "none",
                        "messages": [{"role": "user", "content": prompt}]}
                for k in ("temperature", "top_p", "chat_template_kwargs"):
                    if k in job: body[k] = job[k]
                out = json.loads(urllib.request.urlopen(urllib.request.Request(API, json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=600).read())
                secs = time.time() - t0
                m = out["choices"][0]["message"]
                content = re.sub(r"^<think>.*?</think>\s*", "", m.get("content") or m.get("reasoning") or "", flags=re.S)
                usage = out.get("usage") or {}
                tps = round(usage.get("completion_tokens", 0) / secs, 1) if secs else None
            json.dump({"id": job["id"], "ok": True, "output": content.strip(),
                       "usage": usage, "seconds": round(secs, 2)}, open(J/"done"/(job["id"]+".result.json"), "w", encoding="utf-8"))
            with open(R/"usage.jsonl", "a", encoding="utf-8") as u:
                u.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "id": job["id"],
                    "type": job.get("type"), "model": job["model"],
                    "prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0),
                    "tok_per_s": tps}) + "\n")
        except Exception as e:
            jid = safe_id(job.get("id"), f.stem)
            json.dump({"id": jid, "ok": False, "error": str(e)}, open(J/"failed"/(jid+".error.json"), "w", encoding="utf-8"))
        run.unlink(missing_ok=True)

if __name__ == "__main__":
    ensure_dirs()
    while True:
        process_once()
        time.sleep(3)
