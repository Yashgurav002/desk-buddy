"""Plain-assert tests for install.py. Uses temp dirs only; never touches real settings/Startup."""
import json
import os
import sys
import tempfile

import install

tmp = tempfile.mkdtemp(prefix="desk-buddy-install-")
settings = os.path.join(tmp, "settings.json")
startup = os.path.join(tmp, "Startup")
startmenu = os.path.join(tmp, "Programs")
py = sys.executable

original = {
    "model": "opus",
    "permissions": {"allow": ["Bash(ls)"]},
    "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo user"}]}],
        "PostToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "echo post"}]}],
    },
}
with open(settings, "w", encoding="utf-8") as f:
    json.dump(original, f)


def load():
    with open(settings, encoding="utf-8") as f:
        return json.load(f)


# merge
assert install.install(settings, startup, py, startmenu)
d = load()
assert d["model"] == "opus" and d["permissions"] == original["permissions"]
assert d["hooks"]["PostToolUse"][0] == original["hooks"]["PostToolUse"][0]
assert d["hooks"]["PreToolUse"][0] == original["hooks"]["PreToolUse"][0]
for ev in install.EVENTS:
    ours = [e for e in d["hooks"][ev] if install._is_ours(e)]
    assert len(ours) == 1, ev
    assert ours[0]["hooks"][0]["command"] == install.hook_command(py)
assert [e for e in d["hooks"]["PreToolUse"] if install._is_ours(e)][0]["matcher"] == "*"
assert os.path.exists(settings + ".bak")
with open(settings + ".bak", encoding="utf-8") as f:
    assert json.load(f) == original
lnk = os.path.join(startup, install.LNK_NAME)
assert os.path.exists(lnk), "shortcut missing"
menu_lnk = os.path.join(startmenu, install.LNK_NAME)
assert os.path.exists(menu_lnk), "start menu shortcut missing"
assert d["statusLine"] == {"type": "command", "command": install.statusline_command(py), "padding": 0}

# idempotent
assert install.install(settings, startup, py, startmenu)
assert load() == d

# uninstall restores original
assert install.uninstall(settings, startup, py, startmenu)
assert load() == original
assert not os.path.exists(lnk) and not os.path.exists(menu_lnk)

# user's own statusLine is left alone by install and uninstall
mine = {"statusLine": {"type": "command", "command": "my-status.sh"}}
own = os.path.join(tmp, "own.json")
with open(own, "w", encoding="utf-8") as f:
    json.dump(mine, f)
assert install.install(own, startup, py, startmenu)
with open(own, encoding="utf-8") as f:
    assert json.load(f)["statusLine"] == mine["statusLine"]
assert install.uninstall(own, startup, py, startmenu)
with open(own, encoding="utf-8") as f:
    assert json.load(f) == mine

# missing settings file: install creates it, uninstall leaves no hooks key
fresh = os.path.join(tmp, "new", "settings.json")
assert install.install(fresh, startup, py, startmenu)
assert install.uninstall(fresh, startup, py, startmenu)
with open(fresh, encoding="utf-8") as f:
    assert json.load(f) == {}

# invalid JSON left untouched
bad = os.path.join(tmp, "bad.json")
with open(bad, "w", encoding="utf-8") as f:
    f.write("{not json")
assert install.install(bad, startup, py, startmenu) is False
assert install.uninstall(bad, startup, py, startmenu) is False
with open(bad, encoding="utf-8") as f:
    assert f.read() == "{not json"
assert not os.path.exists(bad + ".bak")

print("test_install: all passed")
