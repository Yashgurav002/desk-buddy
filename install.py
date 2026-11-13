"""Install/uninstall Desk Buddy: Claude Code hooks + statusLine, Startup and Start Menu shortcuts.

python install.py              install
python install.py --uninstall  uninstall

Frozen (DeskBuddy.exe) mode: commands point at dbhook.exe and shortcuts at DeskBuddy.exe.
Env overrides (tests): DESK_BUDDY_SETTINGS, DESK_BUDDY_STARTUP, DESK_BUDDY_STARTMENU.
"""
import json
import os
import shutil
import subprocess
import sys

FROZEN = bool(getattr(sys, "frozen", False))
HERE = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
DBHOOK = os.path.join(HERE, "dbhook.exe")
_STARTUP = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                        "Start Menu", "Programs", "Startup")
SETTINGS = os.environ.get("DESK_BUDDY_SETTINGS") or os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
STARTUP = os.environ.get("DESK_BUDDY_STARTUP") or _STARTUP
STARTMENU = os.environ.get("DESK_BUDDY_STARTMENU") or os.path.dirname(_STARTUP)
LNK_NAME = "Desk Buddy.lnk"
EVENTS = ["UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "Notification", "SessionEnd"]


def hook_command(python_exe):
    if FROZEN:
        return f'"{DBHOOK}" hook'
    return f'"{python_exe}" "{os.path.join(HERE, "hook.py")}"'


def statusline_command(python_exe):
    if FROZEN:
        return f'"{DBHOOK}" statusline'
    return f'"{python_exe}" "{os.path.join(HERE, "statusline.py")}"'


def _statusline_is_ours(sl):
    cmd = sl.get("command", "") if isinstance(sl, dict) else ""
    return HERE in cmd and ("statusline.py" in cmd or 'dbhook.exe" statusline' in cmd)


def _is_ours(entry):
    cmds = [h.get("command", "") for h in entry.get("hooks", []) if isinstance(h, dict)]
    return any(HERE in c and ("hook.py" in c or 'dbhook.exe" hook' in c) for c in cmds)


def _load(settings_path):
    """Returns the parsed dict, {} if missing. Raises ValueError on invalid JSON."""
    if not os.path.exists(settings_path):
        return {}
    with open(settings_path, encoding="utf-8") as f:
        data = json.load(f)  # JSONDecodeError is a ValueError
    if not isinstance(data, dict):
        raise ValueError("settings.json is not a JSON object")
    return data


def _save(settings_path, data):
    if os.path.exists(settings_path):
        shutil.copy2(settings_path, settings_path + ".bak")
    os.makedirs(os.path.dirname(settings_path) or ".", exist_ok=True)
    tmp = settings_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, settings_path)


def _ps_quote(s):
    return "'" + s.replace("'", "''") + "'"


def shortcut_target(python_exe):
    """(TargetPath, Arguments) for the Startup/Start Menu shortcut."""
    if FROZEN:
        return os.path.join(HERE, "DeskBuddy.exe"), ""
    return (os.path.join(os.path.dirname(python_exe), "pythonw.exe"),
            '"' + os.path.join(HERE, "desk_buddy.pyw") + '"')


def _make_shortcut(folder, python_exe):
    target, args = shortcut_target(python_exe)
    os.makedirs(folder, exist_ok=True)
    lnk = os.path.join(folder, LNK_NAME)
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut({_ps_quote(lnk)});"
          f"$s.TargetPath={_ps_quote(target)};"
          f"$s.Arguments={_ps_quote(args)};"
          f"$s.WorkingDirectory={_ps_quote(HERE)};$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                   check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)


def install(settings_path=SETTINGS, startup_dir=STARTUP, python_exe=sys.executable,
            startmenu_dir=STARTMENU, hooks=True):
    """hooks=False skips settings.json (DeskBuddy.exe first launch without ~/.claude)."""
    if hooks and not _install_hooks(settings_path, python_exe):
        return False
    _make_shortcut(startup_dir, python_exe)
    _make_shortcut(startmenu_dir, python_exe)
    return True


def _install_hooks(settings_path, python_exe):
    try:
        data = _load(settings_path)
    except ValueError as e:
        print(f"Invalid JSON in {settings_path}, not touching it: {e}")
        return False

    cmd = hook_command(python_exe)
    hooks = data.setdefault("hooks", {})
    for event in EVENTS:
        entries = hooks.setdefault(event, [])
        if any(_is_ours(e) for e in entries):
            continue
        entry = {"hooks": [{"type": "command", "command": cmd}]}
        if event in ("PreToolUse", "PostToolUse"):
            entry = {"matcher": "*", **entry}
        entries.append(entry)
    if "statusLine" not in data:
        data["statusLine"] = {"type": "command", "command": statusline_command(python_exe), "padding": 0}
    _save(settings_path, data)
    return True


def uninstall(settings_path=SETTINGS, startup_dir=STARTUP, python_exe=sys.executable,
              startmenu_dir=STARTMENU):
    try:
        data = _load(settings_path)
    except ValueError as e:
        print(f"Invalid JSON in {settings_path}, not touching it: {e}")
        return False

    changed = _statusline_is_ours(data.get("statusLine"))
    if changed:
        del data["statusLine"]
    hooks = data.get("hooks")
    if isinstance(hooks, dict):
        for event in EVENTS:
            if event not in hooks:
                continue
            hooks[event] = [e for e in hooks[event] if not _is_ours(e)]
            if not hooks[event]:
                del hooks[event]
        if not hooks:
            del data["hooks"]
        changed = True
    if changed:
        _save(settings_path, data)

    for folder in (startup_dir, startmenu_dir):
        lnk = os.path.join(folder, LNK_NAME)
        if os.path.exists(lnk):
            os.remove(lnk)
    return True


if __name__ == "__main__":
    ok = uninstall() if "--uninstall" in sys.argv else install()
    print("Done." if ok else "Failed.")
    sys.exit(0 if ok else 1)
