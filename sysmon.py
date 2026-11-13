"""System and app monitoring for Desk Buddy (PRD F1-F4, V1, V5, V8). stdlib + psutil only."""
import json
import os
import time
from collections import deque

import psutil

HEAVY_APPS = ["Cursor", "Kiro", "Chrome", "Notion", "Code", "Docker Desktop", "msedge", "Slack", "Discord"]
HIDDEN = {"system", "idle", "system idle process", "svchost", "registry", "smss", "csrss", "wininit",
          "services", "lsass", "winlogon", "dwm", "explorer", "msmpeng", "fontdrvhost", "memory compression"}
_HEAVY = {h.lower() for h in HEAVY_APPS}
_GB = 1024 ** 3


def display_name(exe):
    base = exe[:-4] if exe.lower().endswith(".exe") else exe
    return base.title() if base.islower() else base


class Monitor:
    def __init__(self, pausebook=None):
        self.pausebook = pausebook
        self._hist = {}  # app name -> deque of (time, ram_mb), ~1 sample/min, last 60
        self._idle_since = {}  # app name -> time it dropped under 1% CPU
        self._ncpu = psutil.cpu_count() or 1
        psutil.cpu_percent(None)  # prime the system-wide counter
        self._user = psutil.Process().username()
        self._own = {}      # pid -> (cached Process owned by this user, ppid); cache keeps cpu_percent state
        self._skip = set()  # pids of other users / SYSTEM: reading them costs ~7 ms each on Windows

    def snapshot(self):
        now = time.time()
        me = os.getpid()
        live = set(psutil.pids())
        self._skip &= live
        new = []
        # ponytail: a skipped pid reused by a user app within one interval is missed until it exits
        for pid in live - self._skip - self._own.keys():
            try:
                p = psutil.Process(pid)
                if p.username() == self._user:
                    new.append(p)
                    continue
            except psutil.Error:
                pass
            self._skip.add(pid)
        if new:  # parents never change, so one bulk lookup only when processes appear
            ppids = getattr(psutil._psplatform, "ppid_map", lambda: None)()
            for p in new:
                try:
                    self._own[p.pid] = (p, ppids.get(p.pid) if ppids is not None else p.ppid())
                except psutil.Error:
                    pass
        procs = {}
        for pid, (p, ppid) in list(self._own.items()):
            try:
                if pid not in live or not p.is_running():
                    raise psutil.NoSuchProcess(pid)
                with p.oneshot():
                    procs[pid] = (display_name(p.name()), ppid, p.memory_info().rss, p.cpu_percent())
            except psutil.Error:
                del self._own[pid]

        groups = {}
        for pid, (name, ppid, rss, cpu) in procs.items():
            if pid in (0, me) or name.lower() in HIDDEN:
                continue
            # children of a heavy app count toward the nearest heavy ancestor
            owner, seen, cur = name, {pid}, ppid
            while cur in procs and cur not in seen:
                seen.add(cur)
                if procs[cur][0].lower() in _HEAVY:
                    owner = procs[cur][0]
                cur = procs[cur][1]
            g = groups.setdefault(owner, {"name": owner, "pids": [], "ram_mb": 0.0, "cpu": 0.0, "idle_min": 0.0})
            g["pids"].append(pid)
            g["ram_mb"] += rss / 1024 ** 2
            g["cpu"] += cpu / self._ncpu

        for name, g in groups.items():
            g["cpu"] = min(g["cpu"], 100.0)
            g["paused"] = bool(self.pausebook and self.pausebook.is_paused(name))
            h = self._hist.setdefault(name, deque(maxlen=60))
            if not h or now - h[-1][0] >= 60:
                h.append((now, g["ram_mb"]))
            if g["paused"]:  # suspended apps read 0% CPU; don't let that look like idleness
                self._idle_since.pop(name, None)
            elif g["cpu"] < 1:
                g["idle_min"] = (now - self._idle_since.setdefault(name, now)) / 60
            else:
                self._idle_since.pop(name, None)
        for name in list(self._idle_since):
            if name not in groups:
                del self._idle_since[name]
        for name in list(self._hist):
            if name not in groups:
                del self._hist[name]

        vm = psutil.virtual_memory()
        return {"cpu": psutil.cpu_percent(None), "ram": vm.percent,
                "ram_used_gb": (vm.total - vm.available) / _GB, "ram_total_gb": vm.total / _GB,
                "apps": sorted(groups.values(), key=lambda a: a["ram_mb"], reverse=True)}

    def leaks(self, min_growth_mb=1000, window_min=30):
        now, out = time.time(), []
        for name, h in self._hist.items():
            win = [s for s in h if now - s[0] <= window_min * 60]
            if len(win) < 2:
                continue
            low = min(win, key=lambda s: s[1])
            growth = win[-1][1] - low[1]
            if growth >= min_growth_mb:
                out.append({"name": name, "growth_mb": growth, "minutes": (win[-1][0] - low[0]) / 60})
        return out


def close_app(pids, timeout=3):
    """Terminate, wait, kill survivors. Returns True if every process is gone."""
    procs, denied = [], False
    for pid in pids:
        try:
            p = psutil.Process(pid)
            p.terminate()
            procs.append(p)
        except (psutil.NoSuchProcess, ValueError):
            pass
        except psutil.AccessDenied:
            denied = True
    _, alive = psutil.wait_procs(procs, timeout=timeout)
    for p in alive:
        try:
            p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    _, alive = psutil.wait_procs(alive, timeout=1)
    return not alive and not denied


class Pressure:
    def __init__(self, threshold=85, hold_s=10, cooldown_s=300):
        self.threshold, self.hold_s, self.cooldown_s = threshold, hold_s, cooldown_s
        self._above_since = None
        self._fired_at = None

    def update(self, ram_pct, now):
        if ram_pct < self.threshold:
            self._above_since = None
            return False
        if self._above_since is None:
            self._above_since = now
        if now - self._above_since < self.hold_s:
            return False
        if self._fired_at is not None and now - self._fired_at < self.cooldown_s:
            return False
        self._fired_at = now
        return True


def pick_suggestion(apps):
    apps = [a for a in apps if not a.get("paused")]
    idle = [a for a in apps if a["idle_min"] >= 10]
    return max(idle or apps, key=lambda a: a["ram_mb"], default=None)


def new_heavy_apps(prev_names, apps):
    return [a["name"] for a in apps if a["name"].lower() in _HEAVY and a["name"] not in prev_names]


def _each(pids, method):
    ok = True
    for pid in pids:
        try:
            getattr(psutil.Process(pid), method)()
        except (psutil.Error, ValueError):
            ok = False
    return ok


def suspend_app(pids):
    """Suspend every pid. True if all were suspended; missing/denied ones don't raise."""
    return _each(pids, "suspend")


def resume_app(pids):
    return _each(pids, "resume")


class PauseBook:
    """Paused apps {name: [pids]} persisted to <home>/paused.json so a crash never leaves apps frozen."""

    def __init__(self, home=None):
        home = home or os.environ.get("DESK_BUDDY_HOME") or os.path.join(os.path.expanduser("~"), ".desk-buddy")
        self.path = os.path.join(home, "paused.json")
        self.paused = {}
        try:
            with open(self.path, encoding="utf-8") as f:
                self.paused = {str(k): [int(p) for p in v] for k, v in json.load(f).items()}
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        self.resume_all()  # leftovers from a crash

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.paused, f)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def pause(self, app):
        self.paused[app["name"]] = list(app["pids"])
        self._save()  # save before suspending: a crash in between still gets resumed
        return suspend_app(app["pids"])

    def resume(self, name):
        ok = resume_app(self.paused.pop(name, []))
        self._save()
        return ok

    def is_paused(self, name):
        return name in self.paused

    def resume_all(self):
        for name in list(self.paused):
            resume_app(self.paused.pop(name))
        self._save()


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def evaluate_rules(rules, snap, now, fired):
    """Rules like {"if_ram_over": 90, "app": "Kiro", "idle_min": 30, "action": "pause"}.
    Returns actions to take; the same rule+app fires at most once per 10 min (fired is mutated)."""
    out = []
    for rule in rules if isinstance(rules, list) else []:
        if not (isinstance(rule, dict) and _num(rule.get("if_ram_over")) and isinstance(rule.get("app"), str)
                and rule.get("action") in ("pause", "close") and _num(rule.get("idle_min", 0))):
            continue
        if snap["ram"] <= rule["if_ram_over"]:
            continue
        for app in snap["apps"]:
            if app["name"].lower() != rule["app"].lower() or app["idle_min"] < rule.get("idle_min", 0):
                continue
            if rule["action"] == "pause" and app.get("paused"):
                continue
            key = (json.dumps(rule, sort_keys=True), app["name"])
            if key in fired and now - fired[key] < 600:
                continue
            fired[key] = now
            out.append({"app": app, "action": rule["action"], "rule": rule})
    return out
