"""Claude Code hook: writes one JSON status file per session. Never fails, never prints."""
import json, os, sys, time

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def agents_dir():
    home = os.environ.get("DESK_BUDDY_HOME") or os.path.join(os.path.expanduser("~"), ".desk-buddy")
    return os.path.join(home, "agents")


def tool_action(tool, inp):
    name = os.path.basename(str(inp.get("file_path") or inp.get("notebook_path") or ""))
    if tool in EDIT_TOOLS:
        return f"Editing {name}"
    if tool == "Read":
        return f"Reading {name}"
    if tool in ("Bash", "PowerShell"):
        return f"Running {str(inp.get('command', ''))[:40]}"
    if tool in ("Grep", "Glob"):
        return "Searching code"
    if tool in ("WebFetch", "WebSearch"):
        return "Browsing the web"
    if tool in ("Task", "Agent"):
        return "Running a subagent"
    return f"Using {tool}"


SHELL_TOOLS = ("Bash", "PowerShell")
LOG_MAX = 12


def add_log(rec, line):
    rec["log"] = ((rec.get("log") or []) + [f"{time.strftime('%H:%M')} {line}"])[-LOG_MAX:]


def output_tail(resp, n=4):
    out = resp.get("stdout") or resp.get("output") or resp.get("stderr") or "" if isinstance(resp, dict) else resp
    lines = [l.rstrip() for l in str(out or "").splitlines() if l.strip()]
    return [l[:70] for l in lines[-n:]]


def main():
    data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    sid = str(data["session_id"])
    if not sid or "/" in sid or "\\" in sid or sid.startswith("."):
        return  # never write outside the agents folder
    d = agents_dir()
    path = os.path.join(d, sid + ".json")
    event = data.get("hook_event_name", "")
    if event == "SessionEnd":
        if os.path.exists(path):
            os.remove(path)
        return
    try:
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
    except Exception:
        rec = {"state": "working", "action": "", "todo_done": 0, "todo_total": 0, "todo_current": ""}
    rec["session_id"] = sid
    rec["project"] = os.path.basename(os.path.normpath(data.get("cwd") or "")) or rec.get("project", "")
    if event == "UserPromptSubmit":
        rec["state"], rec["action"] = "working", "Thinking…"
        add_log(rec, "› " + str(data.get("prompt", "")).replace("\n", " ")[:120])
    elif event == "PostToolUse":
        if data.get("tool_name") not in SHELL_TOOLS:
            return
        for line in output_tail(data.get("tool_response")):
            add_log(rec, "  " + line)
    elif event == "PreToolUse":
        tool = data.get("tool_name", "")
        inp = data.get("tool_input") or {}
        rec["state"], rec["action"] = "working", tool_action(tool, inp)
        if tool in SHELL_TOOLS:
            add_log(rec, "$ " + str(inp.get("command", "")).replace("\n", " ")[:200])
        else:
            add_log(rec, rec["action"])
        if tool == "TodoWrite":
            todos = inp.get("todos") or []
            rec["todo_done"] = sum(1 for t in todos if t.get("status") == "completed")
            rec["todo_total"] = len(todos)
            cur = next((t for t in todos if t.get("status") == "in_progress"), None)
            rec["todo_current"] = (cur.get("activeForm") or cur.get("content") or "") if cur else ""
    elif event == "Stop":
        rec["state"], rec["action"] = "waiting", "Done — waiting for you"
        add_log(rec, "✓ done")
    elif event == "Notification":
        rec["state"], rec["action"] = "needs_you", str(data.get("message", ""))[:60]
        add_log(rec, "⚠ " + rec["action"])
    else:
        return
    rec["updated"] = time.time()
    os.makedirs(d, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    os.replace(tmp, path)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        pass
    os._exit(0)
