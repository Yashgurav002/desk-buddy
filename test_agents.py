import json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from agents import load_agents

home = tempfile.mkdtemp()
env = dict(os.environ, DESK_BUDDY_HOME=home)
AG = os.path.join(home, "agents")


def hook(payload):
    raw = payload if isinstance(payload, (bytes, str)) else json.dumps(payload)
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    t = time.time()
    r = subprocess.run([sys.executable, os.path.join(HERE, "hook.py")], input=raw,
                       capture_output=True, env=env, timeout=10)
    assert r.returncode == 0, r
    assert r.stdout == b"", r.stdout
    return time.time() - t


def rec(sid):
    with open(os.path.join(AG, sid + ".json"), encoding="utf-8") as f:
        return json.load(f)


def ev(name, sid="s1", **kw):
    return dict(session_id=sid, cwd="C:\\code\\portfolio-site", hook_event_name=name, **kw)


def pre(tool, sid="s1", **inp):
    return ev("PreToolUse", sid, tool_name=tool, tool_input=inp)


hook(ev("UserPromptSubmit"))
r = rec("s1")
assert r["project"] == "portfolio-site" and r["state"] == "working" and r["action"] == "Thinking…", r
assert set(r) >= {"session_id", "project", "state", "action", "todo_done", "todo_total", "todo_current", "updated"}

long_cmd = "npm test -- --watch=false --coverage --verbose --long-flag"
cases = [
    (pre("Edit", file_path="C:\\code\\src\\Header.tsx"), "Editing Header.tsx"),
    (pre("Write", file_path="/a/b/x.py"), "Editing x.py"),
    (pre("MultiEdit", file_path="/a/m.py"), "Editing m.py"),
    (pre("NotebookEdit", notebook_path="/a/n.ipynb"), "Editing n.ipynb"),
    (pre("Read", file_path="/a/readme.md"), "Reading readme.md"),
    (pre("Bash", command=long_cmd), "Running " + long_cmd[:40]),
    (pre("Grep", pattern="x"), "Searching code"),
    (pre("Glob", pattern="*"), "Searching code"),
    (pre("WebFetch", url="u"), "Browsing the web"),
    (pre("WebSearch", query="q"), "Browsing the web"),
    (pre("Task"), "Running a subagent"),
    (pre("Agent"), "Running a subagent"),
    (pre("mcp__foo"), "Using mcp__foo"),
]
for payload, want in cases:
    hook(payload)
    got = rec("s1")
    assert got["action"] == want and got["state"] == "working", (got["action"], want)

todos = [{"content": "A", "activeForm": "Doing A", "status": "completed"},
         {"content": "B", "activeForm": "Building hero", "status": "in_progress"},
         {"content": "C", "status": "pending"}]
hook(pre("TodoWrite", todos=todos))
r = rec("s1")
assert (r["todo_done"], r["todo_total"], r["todo_current"]) == (1, 3, "Building hero"), r
hook(pre("TodoWrite", todos=[{"content": "Only content", "status": "in_progress"}]))
assert rec("s1")["todo_current"] == "Only content"
hook(pre("TodoWrite", todos=todos))

hook(ev("Stop"))
r = rec("s1")
assert r["state"] == "waiting" and r["action"] == "Done — waiting for you", r
assert (r["todo_done"], r["todo_total"], r["todo_current"]) == (1, 3, "Building hero"), "todos kept"

hook(ev("Notification", message="Claude needs your permission to use Bash " + "x" * 100))
r = rec("s1")
assert r["state"] == "needs_you" and len(r["action"]) == 60 and r["action"].startswith("Claude needs"), r

assert all(n.endswith(".json") for n in os.listdir(AG)), os.listdir(AG)  # no temp leftovers

hook(ev("SessionEnd"))
assert not os.path.exists(os.path.join(AG, "s1.json"))
hook(ev("SessionEnd"))  # already gone: still exits 0

# bad stdin never breaks Claude Code
for bad in [b"", b"not json", b"{}", b"[1,2]", b"\xff\xfe",
            json.dumps({"session_id": "../evil", "hook_event_name": "Stop"})]:
    hook(bad)
assert not os.path.exists(os.path.join(home, "evil.json"))

# speed: < 200 ms (best of 3 to skip cold-start noise)
best = min(hook(ev("UserPromptSubmit", sid="speed")) for _ in range(3))
assert best < 0.2, best

# load_agents: ordering, staleness, corrupt tolerance
for f in os.listdir(AG):
    os.remove(os.path.join(AG, f))
now = 1_000_000.0


def put(sid, state, age_s):
    with open(os.path.join(AG, sid + ".json"), "w", encoding="utf-8") as f:
        json.dump({"session_id": sid, "project": sid, "state": state, "action": "", "todo_done": 0,
                   "todo_total": 0, "todo_current": "", "updated": now - age_s}, f)


put("wait_old", "waiting", 600)
put("wait_new", "waiting", 10)
put("work", "working", 300)
put("need", "needs_you", 900)
put("stale", "working", 31 * 60)
with open(os.path.join(AG, "corrupt.json"), "w") as f:
    f.write("{broken")
got = [a["session_id"] for a in load_agents(home=home, now=now)]
assert got == ["need", "work", "wait_new", "wait_old"], got
assert not os.path.exists(os.path.join(AG, "stale.json")), "stale file should be deleted"
assert load_agents(home=os.path.join(home, "nope")) == []

# end to end: hook -> load_agents
hook(ev("Notification", sid="e2e", message="Waiting for permission: Bash"))
a = load_agents(home=home)
assert a[0]["session_id"] == "e2e" and a[0]["state"] == "needs_you", a

# activity log: prompt, command, its output tail, non-shell PostToolUse ignored, capped at 12
hook(ev("UserPromptSubmit", sid="lg", prompt="fix the header"))
hook(pre("PowerShell", sid="lg", command="npm test"))
hook(ev("PostToolUse", sid="lg", tool_name="PowerShell", tool_response={"stdout": "a\n\nb\nc\nd\ne\n"}))
hook(ev("PostToolUse", sid="lg", tool_name="Read", tool_response={"stdout": "secret"}))
log = rec("lg")["log"]
assert [l.split(" ", 1)[1] for l in log] == ["› fix the header", "$ npm test", "  b", "  c", "  d", "  e"], log
for i in range(15):
    hook(pre("Read", sid="lg", file_path=f"f{i}.py"))
log = rec("lg")["log"]
assert len(log) == 12 and log[-1].endswith("Reading f14.py"), log

print("test_agents: all passed")
