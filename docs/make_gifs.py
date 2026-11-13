"""Record the README GIFs by driving the real Panel with fake data.

python docs/make_gifs.py            -> docs/demo.gif, agents.gif, apps.gif, usage.gif
python docs/make_gifs.py --frames   also dumps every 10th frame as PNG to a temp dir (prints where)

Uses a temp DESK_BUDDY_HOME and port 47995, never pauses a real process (all pids are []),
and grabs frames with PIL.ImageGrab from the window's on-screen box, so keep it unobstructed.
"""
import ctypes
import os
import sys
import tempfile

HOME = tempfile.mkdtemp(prefix="db-gifs-")
os.environ["DESK_BUDDY_HOME"] = HOME
os.environ["DESK_BUDDY_PORT"] = "47995"
with open(os.path.join(HOME, "state.json"), "w") as f:
    f.write('{"x": 120, "y": 60}')  # away from the corner where a real panel usually sits
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # 1:1 pixels, so ImageGrab and tk agree
except Exception:
    pass

from PIL import Image, ImageDraw, ImageGrab  # noqa: E402

DOCS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(DOCS))
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("desk_buddy", os.path.join(os.path.dirname(DOCS), "desk_buddy.pyw"))
db = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(db)

FPS, MARGIN, DESK = 10, 16, (38, 41, 50)  # frame rate, desktop border, desktop colour
TOTAL_GB = 16.0


def app(name, gb, cpu=0.0, idle=0):
    return {"name": name, "pids": [], "ram_mb": gb * 1024, "cpu": cpu, "idle_min": idle, "paused": False}


def snap(cpu, ram, apps):
    return {"cpu": cpu, "ram": ram, "ram_used_gb": TOTAL_GB * ram / 100, "ram_total_gb": TOTAL_GB, "apps": apps}


class Rec:
    """Holds a Panel, grabs frames, draws a fake cursor on top, writes the GIF."""

    def __init__(self, panel):
        self.p, self.frames, self.cur, self.n = panel, [], None, 0

    def show(self, **changes):
        for k, v in changes.items():
            setattr(self.p, k, v)
        self.p.redraw()

    def grab(self, ring=0):
        p = self.p
        p.root.lift()
        p.root.update()
        if self.n % 4 == 0 and p.cv.find_withtag("bob"):  # the 400 ms face bob, at 10 fps
            p.bob = -p.bob
            p.cv.move("bob", 0, 2 * p.bob)
            p.root.update()
        self.n += 1
        x, y = p.root.winfo_rootx(), p.root.winfo_rooty()
        img = ImageGrab.grab(bbox=(x, y, x + p.root.winfo_width(), y + p.root.winfo_height())).convert("RGB")
        self.frames.append((img, self.cur, ring))

    def hold(self, sec):
        for _ in range(max(1, round(sec * FPS))):
            self.grab()

    def find(self, text, row=None):
        """Centre of the canvas text item `text` (on the same line as `row` text, if given)."""
        cv = self.p.cv
        items = [i for i in cv.find_all() if cv.type(i) == "text"]
        ry = None
        if row:
            ry = next(cv.coords(i)[1] for i in items if cv.itemcget(i, "text").startswith(row))
        for i in items:
            if (cv.itemcget(i, "text").startswith(text) or (len(text) > 3 and text in cv.itemcget(i, "text"))) and (ry is None or abs(cv.coords(i)[1] - ry) < 3):
                x1, y1, x2, y2 = cv.bbox(i)
                return i, ((x1 + x2) // 2, (y1 + y2) // 2)
        raise LookupError(text)

    def move(self, to, sec=0.6):
        start = self.cur or (to[0] - 60, to[1] + 80)
        steps = max(1, round(sec * FPS))
        for k in range(1, steps + 1):
            t = k / steps
            t = t * t * (3 - 2 * t)  # ease in-out
            self.cur = (start[0] + (to[0] - start[0]) * t, start[1] + (to[1] - start[1]) * t)
            self.grab()

    def click(self, text, row=None):
        """Move the fake cursor to an item and run its real click handler (what on_press does)."""
        item, pos = self.find(text, row)
        self.move(pos)
        for r in (8, 12):
            self.grab(ring=r)
        tag = next(t for t in self.p.cv.gettags(item) if t in self.p.actions)
        self.p.actions[tag]()
        self.grab(ring=16)
        self.move((pos[0] + 14, pos[1] + 22), 0.3)  # step off the label so it stays readable

    def wheel(self, delta):
        self.p.on_wheel(db._Wheel(self.cur[1], delta))
        self.grab()

    def save(self, name):
        w = max(f.width for f, _, _ in self.frames) + 2 * MARGIN
        h = max(f.height for f, _, _ in self.frames) + 2 * MARGIN
        boards = []
        for f, cur, ring in self.frames:
            b = Image.new("RGB", (w, h), DESK)
            b.paste(f, (MARGIN, MARGIN))
            if cur:  # fake cursor, drawn on the board so it can leave the panel
                d = ImageDraw.Draw(b)
                cx, cy = cur[0] + MARGIN, cur[1] + MARGIN
                if ring:
                    d.ellipse((cx - ring, cy - ring, cx + ring, cy + ring), outline=db.LIME, width=2)
                d.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill="#ffffff", outline="#000000", width=2)
            boards.append(b)
        # one shared palette from a strip of sample frames: small file, no colour flicker
        sample = Image.new("RGB", (w, h * 6))
        for k, f in enumerate(boards[:: max(1, len(boards) // 6)][:6]):
            sample.paste(f, (0, h * k))
        pal = sample.quantize(colors=48, method=Image.Quantize.MEDIANCUT)
        out = [b.quantize(palette=pal, dither=Image.Dither.NONE) for b in boards]
        path = os.path.join(DOCS, name)
        out[0].save(path, save_all=True, append_images=out[1:], duration=1000 // FPS, loop=0, optimize=True)
        print(f"{name}: {len(out)} frames, {w}x{h}, {os.path.getsize(path) / 1024:.0f} KB")
        if "--frames" in sys.argv:
            d = os.path.join(HOME, "frames")
            os.makedirs(d, exist_ok=True)
            for k in range(0, len(boards), 10):
                boards[k].save(os.path.join(d, f"{name[:-4]}_{k:03d}.png"))
            print("frames in", d)
        self.frames, self.cur = [], None


def new_panel():
    p = db.Panel(selftest=True)
    p.root.tk.call("tk", "scaling", 96 / 72)
    p.muted = True
    return p


# ---- the four scenes ----

def demo(rec):
    p = rec.p
    apps = [app("Cursor", 4.6, 14), app("Kiro", 3.1, 0.2, idle=20), app("Chrome", 2.4, 6),
            app("Notion", 0.9, 1), app("Slack", 0.6, 0, idle=12), app("Spotify", 0.3, 1),
            app("Terminal", 0.2), app("Discord", 0.2)]
    p.agents = [{"session_id": "a", "project": "landing-page", "state": "working",
                 "action": "Editing Hero.tsx", "todo_done": 3, "todo_total": 5, "todo_current": "Wire up signup form"}]
    for k in range(13):  # RAM climbs 72% -> 90%
        ram = 72 + 1.5 * k
        rec.show(snap=snap(48 + 2 * k, ram, apps))
        rec.hold(0.15)
    kiro = apps[1]
    rec.show(banner=(f"RAM 90% — Kiro idle 20m {db.fmt_ram(kiro['ram_mb'])}. Close it?", kiro))
    rec.hold(1.4)
    rec.click("⏸", row="Kiro")
    rec.show(banner=None)
    for k in range(8):  # pressure eases
        rec.show(snap=snap(72 - 4 * k, 90 - 1.25 * k, apps))
        rec.hold(0.15)
    rec.move((db.W - 30, 330), 0.5)
    rec.hold(1.6)
    rec.save("demo.gif")


def agents_scene(rec):
    p = rec.p
    p.snap = snap(41, 63, [app("Cursor", 3.8, 9), app("Chrome", 2.1, 3), app("Spotify", 0.3, 1)])
    p.usage = {"five_hour": None, "seven_day": None,
               "sessions": {"a": {"model": "Opus", "ctx_pct": 31, "cost_usd": 0.58}}}
    a = {"session_id": "a", "project": "recipe-api", "state": "working", "action": "Running npm test",
         "todo_done": 2, "todo_total": 5, "todo_current": "Add auth middleware",
         "log": ["14:02 › add login + tests", "14:02 Reading src/server.ts"]}
    b = {"session_id": "b", "project": "blog-redesign", "state": "waiting", "action": "Done: dark mode toggle",
         "todo_done": 0, "todo_total": 0}
    rec.show(agents=[a, b])
    rec.hold(1.6)
    rec.click("recipe-api")
    rec.move((db.W + 6, 170), 0.4)  # park in the margin while the log streams
    stream = ["14:03 Editing src/auth.ts", "14:03 $ npm test", "14:03   12 passed, 1 failed",
              "14:04 Editing src/auth.ts", "14:04 $ npm test", "14:04   13 passed"]
    for k, line in enumerate(stream):
        a["log"] = (a["log"] + [line])[-7:]
        if k == 2:
            a.update(todo_done=3, todo_current="Write token tests")
        if k == 5:
            a.update(todo_done=4, todo_current="Update README", action="Editing README.md")
        rec.show()
        rec.hold(0.5)
    rec.hold(0.6)
    a.update(state="needs_you", action="Waiting for permission: Bash")
    a["log"] = (a["log"] + ["14:05 ⚠ Waiting for permission: Bash"])[-7:]
    rec.show(agents=[a, b])
    rec.hold(2.2)
    rec.save("agents.gif")


def apps_scene(rec):
    p = rec.p
    p.root.winfo_screenheight = lambda: 380 + 22 * 9  # cap the expanded list at 9 rows for a compact GIF
    names = [("Cursor", 3.9, 11), ("Chrome", 2.6, 4), ("Kiro", 2.2, 0, 34), ("Notion", 0.9, 1), ("Slack", 0.6, 0, 15),
             ("Spotify", 0.4, 1), ("Docker", 0.4, 2), ("Discord", 0.3, 0), ("Figma", 0.3, 0, 22), ("Terminal", 0.2, 0),
             ("Zoom", 0.2, 0, 48), ("OneDrive", 0.1, 0), ("Python", 0.1, 3), ("Postman", 0.1, 0, 61)]
    rec.show(snap=snap(37, 71, [app(*n) for n in names]), agents=[])
    rec.hold(1.2)
    rec.click("▾")
    rec.hold(0.8)
    _, pos = rec.find("Spotify")
    rec.move(pos, 0.5)
    for _ in range(3):
        rec.wheel(-120)
        rec.hold(0.5)
    rec.wheel(120)
    rec.hold(0.6)
    rec.click("show less")  # "4–12 of 14 · ▴ show less"
    rec.hold(1.4)
    rec.save("apps.gif")


def usage_scene(rec):
    p = rec.p
    now = db.time.time()
    p.usage = {"five_hour": {"pct": 42, "resets_at": now + 7830}, "seven_day": {"pct": 18, "resets_at": now + 273630},
               "sessions": {}}
    rec.show(snap=snap(34, 58, [app("Cursor", 3.4, 7), app("Chrome", 1.9, 2), app("Slack", 0.5, 0)]), agents=[])
    rec.hold(1.2)
    rec.click("5h 42%")
    rec.hold(1.8)
    rec.click("^")
    rec.move((db.W - 120, 70), 0.6)
    rec.hold(2.0)
    rec.click("v")
    rec.hold(1.0)
    rec.save("usage.gif")


def main():
    for scene in (demo, agents_scene, apps_scene, usage_scene):
        p = new_panel()
        try:
            scene(Rec(p))
        finally:
            p.cleanup()
            p.root.destroy()
    big = [n for n in ("demo.gif", "agents.gif", "apps.gif", "usage.gif")
           if os.path.getsize(os.path.join(DOCS, n)) >= 3 * 1024 * 1024]
    assert not big, f"over 3 MB: {big}"


if __name__ == "__main__":
    main()
