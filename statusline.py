"""Claude Code statusLine command: saves usage to <home>/usage/<sid>.json, prints one short line.
Never raises, always exits 0."""
import json, os, sys, time


def usage_dir():
    home = os.environ.get("DESK_BUDDY_HOME") or os.path.join(os.path.expanduser("~"), ".desk-buddy")
    return os.path.join(home, "usage")


def to_epoch(v):
    """resets_at may be epoch seconds or an ISO string; returns float or None."""
    try:
        return float(v)
    except (TypeError, ValueError):
        pass
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def window(w):
    if not isinstance(w, dict) or num(w.get("used_percentage")) is None:
        return None
    return {"pct": num(w["used_percentage"]), "resets_at": to_epoch(w.get("resets_at"))}


def build(data):
    model = data.get("model")
    model = (model.get("display_name") or model.get("id") or "") if isinstance(model, dict) else str(model or "")
    rl = data.get("rate_limits") or {}
    rl = rl if isinstance(rl, dict) else {}
    return {
        "session_id": str(data.get("session_id") or ""),
        "model": model,
        "ctx_pct": num((data.get("context_window") or {}).get("used_percentage")),
        "cost_usd": num((data.get("cost") or {}).get("total_cost_usd")),
        "five_hour": window(rl.get("five_hour")),
        "seven_day": window(rl.get("seven_day")),
        "updated": time.time(),
    }


def line(rec):
    parts = [rec["model"]] if rec["model"] else []
    if rec["ctx_pct"] is not None:
        parts.append(f"ctx {rec['ctx_pct']:.0f}%")
    for key, label in (("five_hour", "5h"), ("seven_day", "wk")):
        if rec[key]:
            parts.append(f"{label} {rec[key]['pct']:.0f}%")
    return " · ".join(parts)


def main():
    data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    rec = build(data)
    sid = rec["session_id"]
    if sid and "/" not in sid and "\\" not in sid and not sid.startswith("."):
        d = usage_dir()
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, sid + ".json")
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        os.replace(tmp, path)
    sys.stdout.buffer.write(line(rec).encode("utf-8"))
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        pass
    os._exit(0)
