import subprocess
import sys
import time

import json
import os
import tempfile
from collections import deque

import psutil

from sysmon import (Monitor, PauseBook, Pressure, close_app, display_name, evaluate_rules, new_heavy_apps,
                    pick_suggestion, resume_app, suspend_app)


def app(name, ram, idle=0.0):
    return {"name": name, "pids": [1], "ram_mb": ram, "cpu": 0.0, "idle_min": idle}


# display names
assert display_name("chrome.exe") == "Chrome"
assert display_name("Cursor.exe") == "Cursor"
assert display_name("Docker Desktop.exe") == "Docker Desktop"

# Pressure: hold, fire once, cooldown, reset on drop
p = Pressure(threshold=85, hold_s=10, cooldown_s=300)
assert not p.update(90, 0)
assert not p.update(90, 9)
assert p.update(90, 10)
assert not p.update(90, 11)
assert not p.update(90, 309)
assert p.update(90, 310)
p = Pressure()
assert not p.update(90, 0)
assert not p.update(50, 5)          # dropped below: hold timer resets
assert not p.update(90, 6)
assert not p.update(90, 15)
assert p.update(90, 16)

# pick_suggestion
assert pick_suggestion([]) is None
assert pick_suggestion([app("A", 100), app("B", 300)])["name"] == "B"
assert pick_suggestion([app("A", 100, idle=12), app("B", 300, idle=2), app("C", 200, idle=20)])["name"] == "C"

# new_heavy_apps
apps = [app("Cursor", 1), app("Kiro", 1), app("Notepad", 1), app("Msedge", 1)]
assert new_heavy_apps({"Cursor"}, apps) == ["Kiro", "Msedge"]
assert new_heavy_apps({"Cursor", "Kiro", "Msedge"}, apps) == []

# real snapshot shape
m = Monitor()
m.snapshot()
time.sleep(0.5)
s = m.snapshot()
for k in ("cpu", "ram", "ram_used_gb", "ram_total_gb"):
    assert isinstance(s[k], float), k
assert 0 <= s["cpu"] <= 100 and 0 < s["ram"] <= 100 and 0 < s["ram_used_gb"] < s["ram_total_gb"]
assert s["apps"], "no apps found"
for a in s["apps"]:
    assert set(a) == {"name", "pids", "ram_mb", "cpu", "idle_min", "paused"}
    assert a["paused"] is False
    assert isinstance(a["name"], str) and a["pids"] and all(isinstance(x, int) for x in a["pids"])
    assert 0 <= a["cpu"] <= 100 and a["ram_mb"] >= 0 and a["idle_min"] >= 0
    assert a["name"].lower() not in ("svchost", "system", "explorer", "dwm")
rams = [a["ram_mb"] for a in s["apps"]]
assert rams == sorted(rams, reverse=True)
import os
assert all(os.getpid() not in a["pids"] for a in s["apps"])

# close_app on our own child
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
assert close_app([child.pid])
assert child.wait(5) is not None
assert close_app([child.pid]) is True     # already gone: no raise
close_app([2 ** 22 + 7])                  # never existed: no raise

# pick_suggestion skips paused apps
assert pick_suggestion([dict(app("A", 900, idle=30), paused=True), app("B", 100)])["name"] == "B"

# suspend/resume our own child; PauseBook pause, resume and crash recovery (temp home only)
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
try:
    cp = psutil.Process(child.pid)
    assert suspend_app([child.pid])
    assert cp.status() == psutil.STATUS_STOPPED, cp.status()
    assert resume_app([child.pid])
    assert cp.status() == psutil.STATUS_RUNNING, cp.status()
    assert suspend_app([2 ** 22 + 7]) is False and resume_app([2 ** 22 + 7]) is False  # missing: no raise

    home = tempfile.mkdtemp()
    book = PauseBook(home)
    a = {"name": "Sleeper", "pids": [child.pid], "ram_mb": 1.0, "cpu": 0.0, "idle_min": 0.0}
    assert book.pause(a) and book.is_paused("Sleeper")
    assert cp.status() == psutil.STATUS_STOPPED
    with open(os.path.join(home, "paused.json")) as f:
        assert json.load(f) == {"Sleeper": [child.pid]}
    assert book.resume("Sleeper") and not book.is_paused("Sleeper")
    assert cp.status() == psutil.STATUS_RUNNING

    # snapshot reports paused from the pausebook (fake an entry; no real process suspended)
    book.paused["Python"] = []
    m2 = Monitor(pausebook=book)
    snap = m2.snapshot()
    py = [x for x in snap["apps"] if x["name"] == "Python"]
    assert py and py[0]["paused"] is True and py[0]["idle_min"] == 0
    book.paused.clear()

    # crash: paused, then a fresh PauseBook (new process start) resumes and clears
    book.pause(a)
    assert cp.status() == psutil.STATUS_STOPPED
    book2 = PauseBook(home)
    assert cp.status() == psutil.STATUS_RUNNING and not book2.is_paused("Sleeper")
    with open(os.path.join(home, "paused.json")) as f:
        assert json.load(f) == {}
    book2.pause(a)
    book2.resume_all()
    assert cp.status() == psutil.STATUS_RUNNING and book2.paused == {}
    with open(os.path.join(home, "paused.json"), "w") as f:
        f.write("{garbage")
    PauseBook(home)  # corrupt file: no raise
finally:
    psutil.Process(child.pid).resume() if child.poll() is None else None
    child.kill()
    child.wait(5)

# leaks with fake history
m3 = Monitor()
t = time.time()
m3._hist = {
    "Chrome": deque([(t - 1800 + i * 60, 1000 + i * 45) for i in range(31)], maxlen=60),  # +1350 MB / 30 min
    "Steady": deque([(t - 1800 + i * 60, 2000) for i in range(31)], maxlen=60),
    "Old": deque([(t - 7200, 100), (t - 3700, 3000)], maxlen=60),  # growth outside the window
}
lk = m3.leaks()
assert [x["name"] for x in lk] == ["Chrome"], lk
assert abs(lk[0]["growth_mb"] - 1350) < 1 and abs(lk[0]["minutes"] - 30) < 0.1
assert m3.leaks(min_growth_mb=2000) == []
# history is bounded: ~1 sample/min, 60 per app
m3._hist = {}
m3.snapshot(); m3.snapshot()
assert all(len(h) == 1 and h.maxlen == 60 for h in m3._hist.values())

# evaluate_rules
apps = [dict(app("Kiro", 3000, idle=40), paused=False), dict(app("Chrome", 2000, idle=5), paused=False),
        dict(app("Slack", 500, idle=60), paused=True)]
snap = {"ram": 92.0, "apps": apps}
rules = [{"if_ram_over": 90, "app": "Kiro", "idle_min": 30, "action": "pause"},
         {"if_ram_over": 90, "app": "chrome", "idle_min": 30, "action": "close"},  # not idle long enough
         {"if_ram_over": 90, "app": "Slack", "action": "pause"},                   # already paused
         {"if_ram_over": 95, "app": "Kiro", "action": "close"},                    # RAM not over
         {"if_ram_over": "x", "app": "Kiro", "action": "pause"},                   # invalid
         {"if_ram_over": 90, "app": "Kiro", "action": "nuke"},                     # invalid
         "junk", {"app": "Kiro", "action": "pause"}]
fired = {}
out = evaluate_rules(rules, snap, 1000, fired)
assert [(o["app"]["name"], o["action"]) for o in out] == [("Kiro", "pause")] and out[0]["rule"] is rules[0]
assert evaluate_rules(rules, snap, 1500, fired) == []          # within 10 min
assert len(evaluate_rules(rules, snap, 1600, fired)) == 1      # 10 min later
assert evaluate_rules([{"if_ram_over": 90, "app": "Chrome", "action": "close"}], snap, 0, {})[0]["action"] == "close"
assert evaluate_rules(None, snap, 0, {}) == [] and evaluate_rules(rules, {"ram": 50.0, "apps": apps}, 0, {}) == []

print("test_sysmon: OK")
