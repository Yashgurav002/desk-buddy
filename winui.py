"""Windows tray icon, balloon notifications, Win+Shift+D hotkey, fullscreen check.

Callbacks (on_toggle, on_quit) run on the tray's own win32 thread, NOT the tk
thread. The caller must marshal them to tk, e.g. push into a queue.Queue and
poll it with root.after(...).

If pywin32 is missing or broken, the module still imports: Tray is a no-op and
fullscreen_active() returns False.
"""
import threading

try:
    import win32api
    import win32con
    import win32gui
except Exception:  # missing or broken pywin32
    win32api = win32con = win32gui = None

_SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd"}
_WM_TRAY = 0x0400 + 20  # WM_USER + 20
_HOTKEY_ID = 1
_MENU_TOGGLE, _MENU_QUIT = 1, 2


def _lime_icon():
    """A 16x16 lime dot built in memory (raw 32-bit icon bitmap, no PIL); stock icon if that fails."""
    try:
        import struct
        px = b"".join(b"\x35\xe6\xa3\xff" if (x - 7.5) ** 2 + (y - 7.5) ** 2 <= 30 else b"\0\0\0\0"
                      for y in range(16) for x in range(16))  # BGRA, symmetric so row order is moot
        data = struct.pack("<IiiHHIIiiII", 40, 16, 32, 1, 32, 0, 0, 0, 0, 0, 0) + px + b"\0" * 64  # + AND mask
        return win32gui.CreateIconFromResource(data, True)
    except Exception:
        return win32gui.LoadIcon(0, win32con.IDI_APPLICATION)


class Tray:
    def __init__(self, on_toggle, on_quit, tooltip="Desk Buddy"):
        self.on_toggle, self.on_quit, self.tooltip = on_toggle, on_quit, tooltip
        self.hwnd = None
        self.hicon = None
        self._thread = None
        self._ready = threading.Event()

    def start(self):
        if win32gui is None or self._thread:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def notify(self, title, msg):
        if not self.hwnd:
            return
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, (
                self.hwnd, 0, win32gui.NIF_INFO, _WM_TRAY, self.hicon,
                self.tooltip, str(msg)[:255], 5000, str(title)[:63],
                win32gui.NIIF_INFO))
        except Exception:
            pass

    def stop(self):
        t = self._thread
        if not t:
            return
        try:
            if self.hwnd:
                win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass
        t.join(5)
        self._thread = None

    # --- win32 thread ---
    def _run(self):
        cls = "DeskBuddyTray%d" % id(self)
        hinst = win32api.GetModuleHandle(None)
        try:
            wc = win32gui.WNDCLASS()
            wc.hInstance = hinst
            wc.lpszClassName = cls
            wc.lpfnWndProc = {
                _WM_TRAY: self._on_tray,
                win32con.WM_HOTKEY: self._on_hotkey,
                win32con.WM_CLOSE: lambda h, m, w, l: win32gui.DestroyWindow(h) or 0,
                win32con.WM_DESTROY: self._on_destroy,
            }
            win32gui.RegisterClass(wc)
            self.hwnd = win32gui.CreateWindow(cls, "Desk Buddy", 0, 0, 0, 0, 0,
                                              0, 0, hinst, None)
            self.hicon = _lime_icon()
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, (
                self.hwnd, 0, win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
                _WM_TRAY, self.hicon, self.tooltip))
            try:
                win32gui.RegisterHotKey(self.hwnd, _HOTKEY_ID,
                                        win32con.MOD_WIN | win32con.MOD_SHIFT | 0x4000,  # MOD_NOREPEAT
                                        ord("D"))
            except Exception:
                pass  # hotkey already taken: carry on without it
        except Exception:
            self.hwnd = None
            self._ready.set()
            return
        self._ready.set()
        try:
            win32gui.PumpMessages()
        finally:
            self.hwnd = None
            try:
                win32gui.UnregisterClass(cls, hinst)
            except Exception:
                pass

    def _call(self, fn):
        try:
            fn()
        except Exception:
            pass

    def _on_tray(self, hwnd, msg, wparam, lparam):
        if lparam == win32con.WM_LBUTTONUP:
            self._call(self.on_toggle)
        elif lparam == win32con.WM_RBUTTONUP:
            menu = win32gui.CreatePopupMenu()
            win32gui.AppendMenu(menu, win32con.MF_STRING, _MENU_TOGGLE, "Show / Hide")
            win32gui.AppendMenu(menu, win32con.MF_STRING, _MENU_QUIT, "Quit")
            x, y = win32gui.GetCursorPos()
            win32gui.SetForegroundWindow(hwnd)
            cmd = win32gui.TrackPopupMenu(
                menu, win32con.TPM_RETURNCMD | win32con.TPM_NONOTIFY | win32con.TPM_RIGHTBUTTON,
                x, y, 0, hwnd, None)
            win32gui.PostMessage(hwnd, win32con.WM_NULL, 0, 0)
            win32gui.DestroyMenu(menu)
            if cmd == _MENU_TOGGLE:
                self._call(self.on_toggle)
            elif cmd == _MENU_QUIT:
                self._call(self.on_quit)
        return 0

    def _on_hotkey(self, hwnd, msg, wparam, lparam):
        if wparam == _HOTKEY_ID:
            self._call(self.on_toggle)
        return 0

    def _on_destroy(self, hwnd, msg, wparam, lparam):
        for undo in (lambda: win32gui.UnregisterHotKey(hwnd, _HOTKEY_ID),
                     lambda: win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (hwnd, 0))):
            self._call(undo)
        win32gui.PostQuitMessage(0)
        return 0


def fullscreen_active():
    """True when the foreground window covers its whole monitor (not the desktop/taskbar)."""
    if win32gui is None:
        return False
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd or win32gui.GetClassName(hwnd) in _SHELL_CLASSES:
            return False
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        mon = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
        ml, mt, mr, mb = win32api.GetMonitorInfo(mon)["Monitor"]
        return l <= ml and t <= mt and r >= mr and b >= mb
    except Exception:
        return False
