"""Reads the usage files written by statusline.py."""
import json, os, time

STALE_S = 30 * 60


def load_usage(home=None, now=None):
    home = home or os.environ.get("DESK_BUDDY_HOME") or os.path.join(os.path.expanduser("~"), ".desk-buddy")
    d = os.path.join(home, "usage")
    now = time.time() if now is None else now
    out = {"five_hour": None, "seven_day": None, "sessions": {}}
    try:
        names = os.listdir(d)
    except OSError:
        return out
    recs = []
    for n in names:
        if not n.endswith(".json"):
            continue
        p = os.path.join(d, n)
        try:
            with open(p, encoding="utf-8") as f:
                rec = json.load(f)
            rec["updated"] = float(rec["updated"])
        except Exception:
            continue  # corrupt or half-written
        if now - rec["updated"] > STALE_S:
            try:
                os.remove(p)
            except OSError:
                pass
            continue
        recs.append(rec)
        out["sessions"][str(rec.get("session_id") or n[:-5])] = {
            k: rec.get(k) for k in ("model", "ctx_pct", "cost_usd")}
    recs.sort(key=lambda r: -r["updated"])
    for key in ("five_hour", "seven_day"):
        for rec in recs:
            w = rec.get(key)
            if isinstance(w, dict) and w.get("pct") is not None:
                r = w.get("resets_at")
                if not (isinstance(r, (int, float)) and r < now):
                    out[key] = {"pct": w["pct"], "resets_at": r}
                break  # newest file that has limits wins
    return out


def fmt_reset(resets_at, now=None):
    now = time.time() if now is None else now
    m = max(0, int((resets_at - now) // 60))
    d, h = m // 1440, m // 60 % 24
    if d:
        return f"{d}d {h}h"
    if m >= 60:
        return f"{h}h {m % 60}m"
    return f"{m}m"
