"""Plain-assert checks for winui.py. Run: python test_winui.py"""
import importlib
import sys
import time

import winui

# 1. Real tray: start, notify, stop; thread exits; callbacks wired.
hits = []
t = winui.Tray(lambda: hits.append("toggle"), lambda: hits.append("quit"), tooltip="Desk Buddy test")
t.start()
assert t.hwnd, "tray window not created"
thread = t._thread
t.notify("Desk Buddy test", "hello from test_winui")
# simulate a left-click on the tray icon and the hotkey
import win32con, win32gui
win32gui.SendMessage(t.hwnd, winui._WM_TRAY, 0, win32con.WM_LBUTTONUP)
win32gui.SendMessage(t.hwnd, win32con.WM_HOTKEY, winui._HOTKEY_ID, 0)
assert hits == ["toggle", "toggle"], hits
time.sleep(0.3)
t.stop()
assert not thread.is_alive(), "tray thread did not exit"
assert t.hwnd is None
t.stop()  # second stop is harmless

# 2. Start/stop twice in one process (window class re-registration).
t2 = winui.Tray(lambda: None, lambda: None)
t2.start(); assert t2.hwnd; t2.stop()

# 3. fullscreen_active returns a bool.
assert isinstance(winui.fullscreen_active(), bool)

# 4. No-op fallback when win32gui can't be imported.
saved = sys.modules.get("win32gui")
sys.modules["win32gui"] = None  # makes `import win32gui` raise ImportError
try:
    fb = importlib.reload(winui)
    assert fb.win32gui is None
    nt = fb.Tray(lambda: None, lambda: None)
    nt.start(); nt.notify("x", "y"); nt.stop()
    assert nt._thread is None and nt.hwnd is None
    assert fb.fullscreen_active() is False
finally:
    sys.modules["win32gui"] = saved
    importlib.reload(winui)

print("test_winui: all passed")
