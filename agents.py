"""Reads the per-session status files written by hook.py."""
import json, os, time

ORDER = {"needs_you": 0, "working": 1, "waiting": 2}


def load_agents(home=None, now=None, stale_min=30):
    home = home or os.environ.get("DESK_BUDDY_HOME") or os.path.join(os.path.expanduser("~"), ".desk-buddy")
    d = os.path.join(home, "agents")
    now = time.time() if now is None else now
    try:
        names = os.listdir(d)
    except OSError:
        return []
    out = []
    for n in names:
        if not n.endswith(".json"):
            continue
        p = os.path.join(d, n)
        try:
            with open(p, encoding="utf-8") as f:
                rec = json.load(f)
            rec["updated"] = float(rec["updated"])
        except Exception:
            continue  # corrupt or half-written: skip
        if now - rec["updated"] > stale_min * 60:
            try:
                os.remove(p)
            except OSError:
                pass
            continue
        out.append(rec)
    out.sort(key=lambda r: (ORDER.get(r.get("state"), 3), -r["updated"]))
    return out
