"""Plain-assert tests for statusline.py and usage.py. Temp DESK_BUDDY_HOME only."""
import json
import os
import subprocess
import sys
import tempfile
import time

import usage

HERE = os.path.dirname(os.path.abspath(__file__))
home = tempfile.mkdtemp(prefix="desk-buddy-usage-")
env = dict(os.environ, DESK_BUDDY_HOME=home)
udir = os.path.join(home, "usage")


def run(payload):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    t = time.time()
    p = subprocess.run([sys.executable, os.path.join(HERE, "statusline.py")], input=raw,
                       capture_output=True, env=env, timeout=10)
    assert p.returncode == 0, p
    return p.stdout.decode("utf-8"), time.time() - t


now = time.time()
full = {
    "session_id": "s1", "model": {"id": "claude-opus", "display_name": "Opus"},
    "context_window": {"used_percentage": 23.4}, "cost": {"total_cost_usd": 0.42},
    "rate_limits": {"five_hour": {"used_percentage": 42, "resets_at": now + 600},
                    "seven_day": {"used_percentage": 18.2, "resets_at": now + 3 * 86400 + 4 * 3600 + 60}},
}
out, dt = run(full)
assert out == "Opus · ctx 23% · 5h 42% · wk 18%", out
assert "\n" not in out
rec = json.load(open(os.path.join(udir, "s1.json"), encoding="utf-8"))
assert set(rec) == {"session_id", "model", "ctx_pct", "cost_usd", "five_hour", "seven_day", "updated"}
assert rec["model"] == "Opus" and rec["ctx_pct"] == 23.4 and rec["cost_usd"] == 0.42
assert rec["five_hour"] == {"pct": 42.0, "resets_at": now + 600}
assert not [n for n in os.listdir(udir) if n.endswith(".tmp")]

# missing rate_limits -> nulls, line skips them
out, _ = run({"session_id": "s2", "model": {"display_name": "Sonnet"}, "context_window": {"used_percentage": 5}})
assert out == "Sonnet · ctx 5%", out
rec2 = json.load(open(os.path.join(udir, "s2.json"), encoding="utf-8"))
assert rec2["five_hour"] is None and rec2["seven_day"] is None and rec2["cost_usd"] is None

# ISO resets_at is converted to epoch
run({"session_id": "s3", "rate_limits": {"five_hour": {"used_percentage": 1, "resets_at": "2030-01-01T00:00:00Z"}}})
assert json.load(open(os.path.join(udir, "s3.json")))["five_hour"]["resets_at"] == 1893456000.0

# garbage stdin and path-escaping session ids: exit 0, nothing written outside
for junk in (b"not json", b"", b"\xff\xfe", json.dumps({"session_id": "../evil"}).encode()):
    run(junk)
assert not os.path.exists(os.path.join(home, "evil.json"))
# speed (generous bound; first run warms the disk cache)
_, dt = run(full)
assert dt < 1.0, dt

# load_usage: limits from newest file that has them (s3 is newest but s1 also has seven_day)
os.remove(os.path.join(udir, "s3.json"))
u = usage.load_usage(home, now=now + 1)
assert u["five_hour"]["pct"] == 42.0 and u["seven_day"]["pct"] == 18.2
assert u["sessions"]["s1"] == {"model": "Opus", "ctx_pct": 23.4, "cost_usd": 0.42}
assert set(u["sessions"]) == {"s1", "s2"}

# expired window is dropped
u = usage.load_usage(home, now=now + 700)
assert u["five_hour"] is None and u["seven_day"] is not None

# corrupt file skipped; stale file removed
with open(os.path.join(udir, "bad.json"), "w") as f:
    f.write("{nope")
old = dict(rec2, session_id="old", updated=now - 31 * 60)
with open(os.path.join(udir, "old.json"), "w") as f:
    json.dump(old, f)
u = usage.load_usage(home, now=now + 1)
assert "old" not in u["sessions"] and "bad" not in u["sessions"]
assert not os.path.exists(os.path.join(udir, "old.json"))
assert os.path.exists(os.path.join(udir, "bad.json"))

# no folder at all
assert usage.load_usage(tempfile.mkdtemp(), now=now) == {"five_hour": None, "seven_day": None, "sessions": {}}

# fmt_reset
assert usage.fmt_reset(now + 2 * 3600 + 10 * 60, now) == "2h 10m"
assert usage.fmt_reset(now + 3 * 86400 + 4 * 3600 + 30, now) == "3d 4h"
assert usage.fmt_reset(now + 45 * 60, now) == "45m"
assert usage.fmt_reset(now - 100, now) == "0m"

print("test_usage: all passed")
