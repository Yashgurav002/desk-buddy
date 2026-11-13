"""Desk Buddy panel (PRD section 4, F1-F6, V1-V9). tkinter + psutil + pywin32 (optional).

python desk_buddy.pyw             run the panel
python desk_buddy.pyw --selftest  render a few frames with fake data, print RSS, exit
"""
import json
import os
import queue
import socket
import sys
import tempfile
import threading
import time
import tkinter as tk
import webbrowser

import psutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agents  # noqa: E402
import notion  # noqa: E402
import sysmon  # noqa: E402
import usage  # noqa: E402
import winui  # noqa: E402

W, PAD, HEAD = 340, 10, 30
BG, CARD, FG, DIM = "#111214", "#1c1d21", "#e8e8ea", "#8a8b90"
LIME, AMBER, RED, TRACK = "#b6f23a", "#f5a524", "#ef4444", "#2c2d33"
FACES = ["#7c5cff", "#22c3ee", "#f472b6", "#34d399", "#fb923c", "#facc15"]
F = ("Segoe UI", 9)
FS = ("Segoe UI", 8)
FB = ("Segoe UI", 9, "bold")
PORT = int(os.environ.get("DESK_BUDDY_PORT", "47653"))
HOME = os.environ.get("DESK_BUDDY_HOME") or os.path.join(os.path.expanduser("~"), ".desk-buddy")
STATE = os.path.join(HOME, "state.json")
NO_USAGE = {"five_hour": None, "seven_day": None, "sessions": {}}


def single_instance():
    """Hold a socket on 127.0.0.1 for the life of the process; None if another panel has it."""
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", PORT))
        return s
    except OSError:
        s.close()
        return None


def load_rules(home=HOME):
    """config.json "rules" list (V8); anything else means no rules."""
    try:
        with open(os.path.join(home, "config.json"), encoding="utf-8") as f:
            rules = json.load(f).get("rules")
        return rules if isinstance(rules, list) else []
    except Exception:
        return []


def level_color(pct):
    return RED if pct >= 90 else AMBER if pct >= 80 else LIME


def fmt_ram(mb):
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb:.0f} MB"


class Panel:
    def __init__(self, selftest=False):
        self.selftest = selftest
        self.root = tk.Tk()
        self.root.title("Desk Buddy")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG)
        self.cv = tk.Canvas(self.root, width=W, height=HEAD, bg=BG, highlightthickness=0)
        self.cv.pack(fill="both", expand=True)
        self.cv.bind("<Button-1>", self.on_press)
        self.cv.bind("<B1-Motion>", self.on_drag)
        self.cv.bind("<ButtonRelease-1>", self.on_release)
        self.cv.bind("<MouseWheel>", self.on_wheel)

        self.collapsed = self.muted = self.show_more = self.show_reset = False
        self.confirm = None          # app name awaiting "Close X? ✓ ✗"
        self.hidden_agents = set()   # session ids dismissed with ✕
        self.open_agent = None       # session id whose activity log is expanded
        self.banner = None           # (text, app)
        self.toast = None            # (text, until)
        self.snap = {"cpu": 0, "ram": 0, "ram_used_gb": 0, "ram_total_gb": 0, "apps": []}
        self.agents, self.tasks = [], []
        self.usage, self.rules = NO_USAGE, []
        self.latest = None           # written by the worker thread, read by the UI
        self.prev_names = None
        self.prev_states = None      # session id -> state, for "needs you" notifications
        self.leak_seen = {}          # app name -> time of last leak warning
        self.fired = {}              # evaluate_rules cooldowns
        self.notes = []              # notifications sent (selftest checks these)
        self.pressure = sysmon.Pressure()
        self.actions = {}
        self.drag = None
        self.bob = 1
        self.scroll = 0              # first app row shown in the expanded list
        self.apps_box = (0, 0)       # y range of the Apps card, for the mouse wheel
        self.visible, self.fs_hidden, self.was_fs = True, False, False

        # selftest gets a throwaway pausebook so it never resumes the real panel's paused apps
        self.book = sysmon.PauseBook(tempfile.mkdtemp() if selftest else HOME)
        self.q = queue.Queue()       # tray/hotkey callbacks arrive on the win32 thread
        self.tray = winui.Tray(lambda: self.q.put("toggle"), lambda: self.q.put("quit"))
        self.tray.start()

        x, y = self.load_pos()
        self.root.geometry(f"+{x}+{y}")
        self.root.after(100, self.poll)
        if not selftest:
            self.mon = sysmon.Monitor(pausebook=self.book)
            threading.Thread(target=self.worker, daemon=True).start()
            threading.Thread(target=self.notion_worker, daemon=True).start()
            self.root.after(200, self.tick)
            self.root.after(400, self.animate)
            self.root.after(2000, self.check_fullscreen)

    # ---- position ----
    def load_pos(self):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        try:
            with open(STATE, encoding="utf-8") as f:
                p = json.load(f)
            return min(max(int(p["x"]), 0), sw - 60), min(max(int(p["y"]), 0), sh - HEAD)
        except Exception:
            return sw - W - 16, 16

    def save_pos(self):
        try:
            os.makedirs(HOME, exist_ok=True)
            with open(STATE, "w", encoding="utf-8") as f:
                json.dump({"x": self.root.winfo_x(), "y": self.root.winfo_y()}, f)
        except OSError:
            pass

    # ---- show / hide / quit ----
    def poll(self):
        while not self.q.empty():
            msg = self.q.get_nowait()
            if msg == "quit":
                self.root.destroy()  # main() cleans up after mainloop returns
                return
            self.toggle()
        self.root.after(100, self.poll)

    def toggle(self):
        if self.visible and not self.fs_hidden:
            self.hide()
        else:
            self.show()

    def hide(self):
        if not self.tray.hwnd:  # no tray to come back from: really quit
            self.root.destroy()
            return
        self.root.withdraw()
        self.visible, self.fs_hidden = False, False

    def show(self):
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.visible, self.fs_hidden = True, False

    def check_fullscreen(self):
        """Hide when a fullscreen app comes to the front, come back when it leaves (edge-triggered,
        so Win+Shift+D still works while the fullscreen app is up)."""
        fs = winui.fullscreen_active()
        if fs and not self.was_fs and self.visible:
            self.root.withdraw()
            self.fs_hidden = True
        elif not fs and self.was_fs and self.fs_hidden:
            self.show()
        self.was_fs = fs
        if not self.selftest:
            self.root.after(2000, self.check_fullscreen)

    def cleanup(self):
        """Never leave apps frozen or a dead tray icon behind. Safe to call twice."""
        self.book.resume_all()
        self.tray.stop()

    def notify(self, title, msg):
        self.notes.append(msg)
        if not self.selftest:
            self.tray.notify(title, msg)

    # ---- background work (never touches tk) ----
    def worker(self):
        while True:
            try:
                self.latest = (self.mon.snapshot(), agents.load_agents(), usage.load_usage(),
                               self.mon.leaks(), load_rules())
            except Exception:
                pass
            time.sleep(2)

    def notion_worker(self):
        while True:
            cfg = notion.load_config()
            self.tasks = notion.fetch_today(cfg["notion_token"], cfg["notion_db_id"]) if cfg else []
            time.sleep(300)

    # ---- UI loop ----
    def tick(self):
        if self.latest:
            snap, ags, self.usage, leaks, self.rules = self.latest
            self.latest = None
            self.apply(snap, ags, leaks=leaks)
        self.root.after(2000, self.tick)

    def apply(self, snap, ags, now=None, leaks=()):
        now = time.time() if now is None else now
        self.snap, self.agents = snap, ags
        names = {a["name"] for a in snap["apps"]}
        if self.prev_names is not None:
            new = sysmon.new_heavy_apps(self.prev_names, snap["apps"])
            if new:
                self.toast = (f"{new[0]} opened — RAM now {snap['ram']:.0f}%", now + 4)
                self.root.after(4100, self.redraw)
        self.prev_names = names

        states = {a.get("session_id"): a.get("state") for a in ags}
        if self.prev_states is not None:
            for a in ags:
                if a.get("state") == "needs_you" and self.prev_states.get(a.get("session_id")) != "needs_you":
                    self.notify(f"{a.get('project', '?')} needs you", str(a.get("action", "")) or "Claude Code")
        self.prev_states = states

        if self.pressure.update(snap["ram"], now):
            app = sysmon.pick_suggestion(snap["apps"])
            if app:
                how = f"idle {app['idle_min']:.0f}m" if app["idle_min"] >= 10 else "is using"
                self.warn(f"RAM {snap['ram']:.0f}% — {app['name']} {how} {fmt_ram(app['ram_mb'])}. Close it?", app)

        for lk in leaks:
            app = next((a for a in snap["apps"] if a["name"] == lk["name"]), None)
            if app and now - self.leak_seen.get(lk["name"], -1e9) >= 3600:
                self.leak_seen[lk["name"]] = now
                self.warn(f"{lk['name']} +{lk['growth_mb'] / 1024:.1f} GB in {lk['minutes']:.0f} min", app)

        done = []
        for r in sysmon.evaluate_rules(self.rules, snap, now, self.fired):
            app = r["app"]
            if r["action"] == "pause":
                self.pause(app, redraw=False)
                done.append(f"paused {app['name']}")
            else:
                self.close(app, redraw=False)
                done.append(f"closed {app['name']}")
        if done:
            self.toast = (f"Auto-rule: {', '.join(done)} (RAM {snap['ram']:.0f}%)", now + 6)
            self.root.after(6100, self.redraw)
        self.redraw()

    def warn(self, text, app):
        """Amber banner + Windows notification + beep (pressure and leak warnings)."""
        self.banner = (text, app)
        self.root.lift()
        self.notify("Desk Buddy", text)
        if not self.muted:
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception:
                pass

    def animate(self):
        if self.cv.find_withtag("bob"):
            self.bob = -self.bob
            self.cv.move("bob", 0, 2 * self.bob)
        self.root.after(400, self.animate)

    # ---- input ----
    def on_press(self, e):
        for t in self.cv.gettags("current"):
            if t in self.actions:
                self.actions[t]()
                return
        if e.y < HEAD:
            self.drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def on_drag(self, e):
        if self.drag:
            self.root.geometry(f"+{e.x_root - self.drag[0]}+{e.y_root - self.drag[1]}")

    def on_release(self, _e):
        if self.drag:
            self.drag = None
            self.save_pos()

    def on_wheel(self, e):
        if self.show_more and self.apps_box[0] <= e.y <= self.apps_box[1]:
            self.scroll += -2 if e.delta > 0 else 2  # clamped in redraw
            self.redraw()

    def act(self, fn):
        tag = f"act{len(self.actions)}"
        self.actions[tag] = fn
        return tag

    def do(self, **changes):
        """Return a callback that sets attributes and redraws."""
        def fn():
            for k, v in changes.items():
                setattr(self, k, v)
            self.redraw()
        return fn

    def close(self, app, redraw=True):
        self.confirm = None
        self.banner = None
        if self.book.is_paused(app["name"]):
            self.book.resume(app["name"])
        threading.Thread(target=sysmon.close_app, args=(app["pids"],), daemon=True).start()
        self.snap["apps"] = [a for a in self.snap["apps"] if a["name"] != app["name"]]
        if redraw:
            self.redraw()

    def pause(self, app, redraw=True):
        self.book.pause(app)
        app["paused"] = True
        if redraw:
            self.redraw()

    def resume(self, app):
        self.book.resume(app["name"])
        app["paused"] = False
        self.redraw()

    def hide_agent(self, sid):
        self.hidden_agents.add(sid)
        self.redraw()

    # ---- drawing ----
    def rrect(self, x1, y1, x2, y2, r=10, **kw):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
               x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.cv.create_polygon(pts, smooth=True, **kw)

    def text(self, x, y, s, fill=FG, font=F, anchor="w", **kw):
        return self.cv.create_text(x, y, text=s, fill=fill, font=font, anchor=anchor, **kw)

    def bar(self, x, y, w, pct, color):
        self.cv.create_rectangle(x, y, x + w, y + 6, fill=TRACK, width=0)
        self.cv.create_rectangle(x, y, x + w * max(0, min(pct, 100)) / 100, y + 6, fill=color, width=0)

    def card(self, y, h, title=None):
        self.rrect(PAD, y, W - PAD, y + h, fill=CARD)
        if title:
            self.text(PAD + 12, y + 14, title, fill=DIM, font=FB)

    def face(self, x, y, color, working, tag=None):
        tags = (("bob",) if working else ()) + ((tag,) if tag else ())
        self.cv.create_oval(x, y, x + 26, y + 26, fill=color, width=0, tags=tags)
        eh = 2 if working and int(time.time()) % 4 == 0 else 5  # blink now and then
        for ex in (x + 8, x + 15):
            self.cv.create_oval(ex, y + 9, ex + 4, y + 9 + eh, fill="#111", width=0, tags=tags)
        self.cv.create_line(x + 8, y + 18, x + 13, y + 20, x + 18, y + 18, fill="#111", smooth=True, tags=tags)

    def limits(self):
        """[(label, pct, resets_at)] for the usage windows that have data."""
        return [(lab, float(w["pct"]), w.get("resets_at"))
                for key, lab in (("five_hour", "5h"), ("seven_day", "wk"))
                for w in [self.usage.get(key)] if w]

    def ctx_line(self, a):
        u = self.usage.get("sessions", {}).get(a.get("session_id")) or {}
        parts = [str(u["model"])] if u.get("model") else []
        if u.get("ctx_pct") is not None:
            parts.append(f"ctx {float(u['ctx_pct']):.0f}%")
        if u.get("cost_usd") is not None:
            parts.append(f"${float(u['cost_usd']):.2f}")
        return " · ".join(parts)

    def redraw(self):
        cv, s = self.cv, self.snap
        cv.delete("all")
        self.actions = {}
        lim = self.limits()
        # header
        cv.create_rectangle(0, 0, W, HEAD, fill=BG, width=0)
        if self.collapsed:
            title = f"CPU {s['cpu']:.0f}% · RAM {s['ram']:.0f}%"
            if lim and lim[0][0] == "5h":
                title += f" · 5h {lim[0][1]:.0f}%"
        else:
            title = "Desk Buddy"
        self.text(PAD + 2, HEAD / 2, "●", fill=level_color(max(s["cpu"], s["ram"])))
        self.text(PAD + 16, HEAD / 2, title, font=FB)
        for i, (sym, fn) in enumerate([("✕", self.hide),
                                       ("v" if self.collapsed else "^", self.do(collapsed=not self.collapsed)),
                                       ("🔇" if self.muted else "🔊", self.do(muted=not self.muted))]):
            self.text(W - PAD - 8 - i * 26, HEAD / 2, sym, fill=DIM, font=("Segoe UI", 10), anchor="center",
                      tags=(self.act(fn),))
        if lim and not self.collapsed:
            top = max(p for _, p, _ in lim)
            self.text(W - PAD - 72, HEAD / 2, " · ".join(f"{lab} {p:.0f}%" for lab, p, _ in lim),
                      fill=RED if top >= 95 else AMBER if top >= 80 else DIM, font=FS, anchor="e",
                      tags=(self.act(self.do(show_reset=not self.show_reset)),))
        y = HEAD
        if not self.collapsed:
            if lim and self.show_reset:
                resets = [f"{'5h resets' if lab == '5h' else 'week'} in {usage.fmt_reset(r)}"
                          for lab, _, r in lim if isinstance(r, (int, float))]
                self.text(PAD + 4, y + 7, " · ".join(resets) or "no reset time yet", fill=DIM, font=FS)
                y += 16
            y = self.draw_body(y + 2)
        h = int(y + (0 if self.collapsed else PAD))
        cv.configure(height=h)
        self.root.geometry(f"{W}x{h}")

    def draw_body(self, y):
        s = self.snap
        if self.toast and time.time() < self.toast[1]:
            self.rrect(PAD, y, W - PAD, y + 28, fill="#23324a")
            self.text(PAD + 12, y + 14, self.toast[0], width=W - 2 * PAD - 24)
            y += 36
        else:
            self.toast = None
        if self.banner:
            text, app = self.banner
            self.rrect(PAD, y, W - PAD, y + 54, fill="#3a2a0e", outline=AMBER)
            self.text(PAD + 12, y + 16, "⚠ " + text, fill=AMBER, width=W - 2 * PAD - 24)
            self.text(PAD + 12, y + 40, "[Close]", fill=FG, font=FB, tags=(self.act(lambda: self.close(app)),))
            self.text(PAD + 70, y + 40, "[Dismiss]", fill=DIM, tags=(self.act(self.do(banner=None)),))
            y += 62

        # system
        self.card(y, 54, "System")
        self.text(PAD + 12, y + 38, "CPU")
        self.bar(PAD + 42, y + 35, 70, s["cpu"], level_color(s["cpu"]))
        self.text(PAD + 118, y + 38, f"{s['cpu']:.0f}%")
        self.text(PAD + 160, y + 38, "RAM")
        self.bar(PAD + 192, y + 35, 70, s["ram"], level_color(s["ram"]))
        self.text(PAD + 268, y + 38, f"{s['ram']:.0f}%")
        self.text(W - PAD - 12, y + 14, f"{s['ram_used_gb']:.1f} / {s['ram_total_gb']:.1f} GB", fill=DIM, anchor="e")
        y += 62

        # apps: expanded list shows as many rows as fit the screen, the mouse wheel scrolls the rest
        apps = s["apps"]
        cap = max(6, (self.root.winfo_screenheight() - 380) // 22)
        if self.show_more:
            self.scroll = max(0, min(self.scroll, len(apps) - cap))
            shown = apps[self.scroll:self.scroll + cap]
        else:
            self.scroll = 0
            shown = apps[:6]
        extra = len(apps) - 6
        h = 28 + 22 * len(shown)
        self.card(y, h, "Apps")
        self.apps_box = (y, y + h)
        if extra > 0:  # toggle lives in the card header so it is always reachable
            label = "▴ show less" if self.show_more else f"▾ +{extra} more"
            if self.show_more and len(apps) > cap:
                label = f"{self.scroll + 1}–{self.scroll + len(shown)} of {len(apps)} · {label}"
            self.text(W - PAD - 12, y + 14, label, fill=LIME, font=FB, anchor="e",
                      tags=(self.act(self.do(show_more=not self.show_more)),))
        ry = y + 36
        for i, a in enumerate(shown):
            paused = a.get("paused")
            self.cv.create_rectangle(PAD + 12, ry - 5, PAD + 22, ry + 5,
                                     fill=TRACK if paused else FACES[(i + self.scroll) % len(FACES)], width=0)
            if self.confirm == a["name"]:
                self.text(PAD + 30, ry, f"Close {a['name']}?", fill=AMBER, font=FB)
                self.text(W - PAD - 40, ry, "✓", fill=LIME, font=FB, anchor="center", tags=(self.act(
                    lambda a=a: self.close(a)),))
                self.text(W - PAD - 16, ry, "✗", fill=RED, font=FB, anchor="center",
                          tags=(self.act(self.do(confirm=None)),))
                ry += 22
                continue
            if paused:
                self.text(PAD + 30, ry, a["name"][:18], fill=DIM)
                self.text(W - PAD - 52, ry, f"{fmt_ram(a['ram_mb'])} · paused", fill=DIM, anchor="e")
                self.text(W - PAD - 38, ry, "▶", fill=LIME, font=FS, anchor="center",
                          tags=(self.act(lambda a=a: self.resume(a)),))
            else:
                self.text(PAD + 30, ry, a["name"][:18])
                load = f"idle {a['idle_min']:.0f}m" if a["idle_min"] >= 10 else f"{a['cpu']:.0f}% CPU"
                self.text(W - PAD - 52, ry, f"{fmt_ram(a['ram_mb'])} · {load}", fill=DIM, anchor="e")
                self.text(W - PAD - 38, ry, "⏸", fill=DIM, font=FS, anchor="center",
                          tags=(self.act(lambda a=a: self.pause(a)),))
            self.text(W - PAD - 16, ry, "✕", fill=DIM, anchor="center",
                      tags=(self.act(self.do(confirm=a["name"])),))
            ry += 22
        y += h + 8

        # agents
        ags = [a for a in self.agents if a.get("session_id") not in self.hidden_agents]
        if ags:
            def log_of(a):
                return (a.get("log") or ["(no activity yet)"]) if a.get("session_id") == self.open_agent else []

            def info_of(a):
                return self.ctx_line(a) if a.get("session_id") == self.open_agent else ""
            rows = [(a, 50 + (22 if a.get("todo_total") else 0) + (16 if info_of(a) else 0)
                     + (14 * len(log_of(a)) + 14 if log_of(a) else 0)) for a in ags]
            h = 28 + sum(r for _, r in rows)
            self.card(y, h, f"Claude Code agents ({len(ags)}) · click to expand")
            ry = y + 30
            for a, rh in rows:
                sid, state = a.get("session_id", ""), a.get("state")
                tog = self.act(self.do(open_agent=None if sid == self.open_agent else sid))
                self.cv.create_rectangle(PAD + 4, ry, W - PAD - 30, ry + rh - 4, fill=CARD, width=0, tags=(tog,))
                color = FACES[sum(map(ord, a.get("project", "?"))) % len(FACES)]
                self.face(PAD + 12, ry + 2, color, state == "working", tog)
                self.text(PAD + 48, ry + 8, str(a.get("project", "?"))[:24], font=FB, tags=(tog,))
                if state == "needs_you":
                    self.text(W - PAD - 34, ry + 8, "⚠ needs you", fill=AMBER, font=FB, anchor="e")
                elif state == "waiting":
                    self.text(W - PAD - 34, ry + 8, "waiting", fill=DIM, anchor="e")
                self.text(W - PAD - 16, ry + 8, "✕", fill=DIM, anchor="center",
                          tags=(self.act(lambda sid=sid: self.hide_agent(sid)),))
                self.text(PAD + 48, ry + 27, str(a.get("action", ""))[:40], fill=DIM, tags=(tog,))
                ly = ry + 50
                if a.get("todo_total"):
                    done, total = a.get("todo_done", 0), a["todo_total"]
                    self.text(PAD + 48, ry + 46, f"{done}/{total} {a.get('todo_current') or ''}"[:42], fill=FG)
                    self.bar(PAD + 48, ry + 58, W - 2 * PAD - 64, 100 * done / total, LIME)
                    ly += 22
                info = info_of(a)
                if info:
                    self.text(PAD + 14, ly + 2, info, fill=DIM, font=FS, tags=(tog,))
                    ly += 16
                lines = log_of(a)
                if lines:  # terminal-style recent activity
                    self.cv.create_rectangle(PAD + 8, ly - 4, W - PAD - 8, ly + 14 * len(lines) + 4,
                                             fill="#0b0b0d", width=0, tags=(tog,))
                    for i, line in enumerate(lines):
                        self.text(PAD + 14, ly + 6 + 14 * i, line[:50], fill=LIME if line.startswith(("$", "›")) else DIM,
                                  font=("Consolas", 8), tags=(tog,))
                ry += rh
            y += h + 8

        # notion
        if self.tasks:
            h = 28 + 22 * len(self.tasks)
            self.card(y, h, "Notion · Today")
            ry = y + 36
            for t in self.tasks:
                self.text(PAD + 12, ry, "☐ " + t["title"][:44], tags=(self.act(
                    lambda u=t["url"]: webbrowser.open(u)),))
                ry += 22
            y += h + 8
        return y - 8


class _Wheel:
    def __init__(self, y, delta):
        self.y, self.delta = y, delta


def selftest():
    """Render frames with fake data (no real pids are ever paused), check the v2 states, destroy. Prints RSS."""
    p = Panel(selftest=True)
    real = sysmon.Monitor().snapshot()  # exercise the real monitor once, for a realistic RSS
    apps = [{"name": n, "pids": [], "ram_mb": mb, "cpu": c, "idle_min": idle, "paused": False}
            for n, mb, c, idle in [("Cursor", 4200, 12, 0), ("Kiro", 3100, 0.2, 40), ("Chrome", 2400, 3, 0),
                                   ("Notion", 800, 1, 0), ("Slack", 500, 0, 12), ("Spotify", 300, 1, 0),
                                   ("Terminal", 120, 0, 0), ("Python", 60, 0, 0)]]
    apps += [{"name": f"Helper{i}", "pids": [], "ram_mb": 50 - i, "cpu": 0, "idle_min": 0, "paused": False}
             for i in range(max(6, (p.root.winfo_screenheight() - 380) // 22))]  # just enough to need scrolling
    snap = dict(real, cpu=68.0, ram=88.0, apps=apps)
    now = time.time()
    ags = [{"session_id": "a", "project": "portfolio-site", "state": "working", "action": "Editing Header.tsx",
            "todo_done": 3, "todo_total": 5, "todo_current": "Build hero section", "updated": now,
            "log": ["10:01 › build the hero", "10:02 $ npm test", "10:02   3 passed"]},
           {"session_id": "b", "project": "weather-bot", "state": "needs_you",
            "action": "Waiting for permission: Bash", "todo_done": 0, "todo_total": 0, "updated": now}]
    waiting = [ags[0], dict(ags[1], state="waiting")]
    p.tasks = [{"title": "Send portfolio to recruiter", "url": "https://example.com"}]
    p.usage = {"five_hour": {"pct": 42, "resets_at": now + 7830}, "seven_day": {"pct": 18, "resets_at": now + 273630},
               "sessions": {"a": {"model": "Opus", "ctx_pct": 23, "cost_usd": 0.42}}}
    p.muted = True
    t0 = now
    leak = [{"name": "Chrome", "growth_mb": 1230, "minutes": 30}]
    frames = [
        lambda: p.apply(dict(snap, apps=apps[1:]), waiting, now=t0),  # first frame: Cursor absent, b waiting
        lambda: p.apply(snap, ags, now=t0 + 2),                        # Cursor appears -> toast; b -> needs you
        lambda: p.apply(snap, ags, now=t0 + 12),                       # RAM held >= 85% for 10 s -> banner
        lambda: (p.notes.append("BANNER " + p.banner[0]), p.apply(snap, ags, now=t0 + 14, leaks=leak)),
        lambda: p.apply(snap, ags, now=t0 + 16, leaks=leak),           # same leak again: no repeat
        lambda: setattr(p, "rules", [{"if_ram_over": 80, "app": "Kiro", "idle_min": 30, "action": "pause"}]),
        lambda: p.apply(snap, ags, now=t0 + 18),                       # rule pauses Kiro (fake pids) + toast
        lambda: p.pause(apps[2]), lambda: p.resume(apps[2]),           # Chrome paused, then resumed
        p.do(show_reset=True),
        p.do(show_more=True),
        lambda: p.on_wheel(_Wheel(p.apps_box[0] + 40, -120)),          # wheel down over the Apps card
        p.do(confirm="Notion"), p.do(open_agent="a"), p.do(open_agent="b"), p.animate,
        p.do(collapsed=True),
    ]
    for f in frames:
        f()
        p.root.update()
    texts = [p.cv.itemcget(i, "text") for i in p.cv.find_all() if p.cv.type(i) == "text"]
    assert any("5h 42%" in t for t in texts), texts  # collapsed header
    p.do(collapsed=False, open_agent="a")()
    p.root.update()
    texts = [p.cv.itemcget(i, "text") for i in p.cv.find_all() if p.cv.type(i) == "text"]
    notes = "\n".join(p.notes)
    assert "BANNER RAM 88%" in notes and "Kiro" in notes, notes
    assert "Waiting for permission: Bash" in notes, notes
    assert notes.count("Chrome +1.2 GB in 30 min") == 1, notes
    assert p.banner and "Chrome +1.2 GB" in p.banner[0], p.banner
    assert p.book.is_paused("Kiro") and not p.book.is_paused("Chrome"), p.book.paused
    assert "5h 42% · wk 18%" in texts, texts
    assert any(t.startswith("5h resets in 2h 10m · week in 3d") for t in texts), texts
    assert "Opus · ctx 23% · $0.42" in texts, texts
    assert p.scroll == 2 and any(f" of {len(apps)} · ▴ show less" in t for t in texts), (p.scroll, texts)
    assert not any("not shown" in t for t in texts), texts
    p.do(show_more=False)()  # top of the list again: Kiro's paused row is visible
    texts = [p.cv.itemcget(i, "text") for i in p.cv.find_all() if p.cv.type(i) == "text"]
    assert p.scroll == 0 and "Kiro" in texts, texts
    assert any(t.endswith("· paused") for t in texts) and "▶" in texts and "⏸" in texts, texts
    # fullscreen: hides on the way in, comes back on the way out
    real_fs = winui.fullscreen_active
    try:
        winui.fullscreen_active = lambda: True
        p.check_fullscreen()
        p.root.update()
        assert p.root.state() == "withdrawn", p.root.state()
        winui.fullscreen_active = lambda: False
        p.check_fullscreen()
        p.root.update()
        assert p.root.state() == "normal", p.root.state()
    finally:
        winui.fullscreen_active = real_fs
    # header ✕ hides (when there is a tray), the tray toggle brings it back
    if p.tray.hwnd:
        p.hide()
        p.root.update()
        assert p.root.state() == "withdrawn"
        p.q.put("toggle")
        p.poll()
        p.root.update()
        assert p.root.state() == "normal"
    p.cleanup()
    assert not p.book.paused and p.tray.hwnd is None, (p.book.paused, p.tray.hwnd)
    p.root.destroy()
    print(f"RSS_MB={psutil.Process().memory_info().rss / 1024 ** 2:.1f}")


INSTALLED_MARK = os.path.join(HOME, "installed")


def first_launch_install():
    """DeskBuddy.exe only: install once (shortcuts, plus hooks if ~/.claude exists). True if it did."""
    import install
    if not install.FROZEN or os.path.exists(INSTALLED_MARK):
        return False
    hooks = os.path.isdir(os.path.dirname(install.SETTINGS))
    try:
        if not install.install(hooks=hooks):
            return False
    except Exception:
        return False
    os.makedirs(HOME, exist_ok=True)
    with open(INSTALLED_MARK, "w") as f:
        f.write(install.HERE)
    return True


def main():
    if "--uninstall" in sys.argv:
        import install
        ok = install.uninstall()
        if ok and os.path.exists(INSTALLED_MARK):
            os.remove(INSTALLED_MARK)
        sys.exit(0 if ok else 1)
    lock = single_instance()
    if lock is None:
        return  # another panel is already running
    if "--selftest" in sys.argv:
        selftest()
        return
    installed = first_launch_install()
    p = Panel()
    if installed:
        p.notify("Desk Buddy", "Desk Buddy installed - starts at login")
    try:
        p.root.mainloop()
    finally:
        p.cleanup()


if __name__ == "__main__":
    main()
