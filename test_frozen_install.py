"""Plain-assert tests for install.py frozen (DeskBuddy.exe) mode. Simulates sys.frozen; temp dirs only."""
import importlib
import json
import os
import sys
import tempfile

tmp = tempfile.mkdtemp(prefix="desk-buddy-frozen-")
app = os.path.join(tmp, "DeskBuddy")
exe, dbhook = os.path.join(app, "DeskBuddy.exe"), os.path.join(app, "dbhook.exe")
settings = os.path.join(tmp, "claude", "settings.json")
os.environ.update(DESK_BUDDY_SETTINGS=settings, DESK_BUDDY_STARTUP=os.path.join(tmp, "Startup"),
                  DESK_BUDDY_STARTMENU=os.path.join(tmp, "Programs"))

real_exe = sys.executable
sys.frozen, sys.executable = True, exe
try:
    import install
    importlib.reload(install)
finally:
    del sys.frozen
    sys.executable = real_exe

assert install.FROZEN and install.HERE == app
assert (install.SETTINGS, install.STARTUP, install.STARTMENU) == (
    settings, os.path.join(tmp, "Startup"), os.path.join(tmp, "Programs"))
assert install.hook_command("ignored") == f'"{dbhook}" hook'
assert install.statusline_command("ignored") == f'"{dbhook}" statusline'
assert install.shortcut_target("ignored") == (exe, "")
assert install._is_ours({"hooks": [{"command": install.hook_command(None)}]})
assert not install._is_ours({"hooks": [{"command": install.statusline_command(None)}]})
assert install._statusline_is_ours({"command": install.statusline_command(None)})
assert not install._statusline_is_ours({"command": '"C:\\other\\dbhook.exe" statusline'})

# full round trip with the env-default paths
user = {"model": "opus", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}
os.makedirs(os.path.dirname(settings))
with open(settings, "w", encoding="utf-8") as f:
    json.dump(user, f)
assert install.install()
with open(settings, encoding="utf-8") as f:
    d = json.load(f)
for ev in install.EVENTS:
    assert [h["hooks"][0]["command"] for h in d["hooks"][ev] if install._is_ours(h)] == [f'"{dbhook}" hook'], ev
assert d["statusLine"]["command"] == f'"{dbhook}" statusline'
lnks = [os.path.join(tmp, f, install.LNK_NAME) for f in ("Startup", "Programs")]
assert all(os.path.exists(l) for l in lnks)
assert install.install()  # idempotent
with open(settings, encoding="utf-8") as f:
    assert json.load(f) == d
assert install.uninstall()
with open(settings, encoding="utf-8") as f:
    assert json.load(f) == user
assert not any(os.path.exists(l) for l in lnks)

# hooks=False (no ~/.claude): shortcuts only, settings never created
missing = os.path.join(tmp, "none", "settings.json")
assert install.install(missing, hooks=False)
assert not os.path.exists(missing) and all(os.path.exists(l) for l in lnks)
assert install.uninstall(missing)
assert not any(os.path.exists(l) for l in lnks)

for k in ("DESK_BUDDY_SETTINGS", "DESK_BUDDY_STARTUP", "DESK_BUDDY_STARTMENU"):
    del os.environ[k]
importlib.reload(install)  # leave the module in normal mode for anything imported after us
print("test_frozen_install: all passed")
