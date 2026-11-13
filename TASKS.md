# Desk Buddy — Tasks

Source: `PRD.md`. Status: `[ ]` todo · `[~]` in progress · `[x]` passed tester · `[!]` failed after 3 rounds.
Rules for every task: Python 3.11 standard library + `psutil` only. No new dependencies. Each module ships with one `test_<module>.py` made of plain asserts that exits non-zero on failure. Tests must not touch the real `~/.claude`, the real Startup folder, or kill real user apps.

## Wave 1 — modules (run in parallel)

### T1 · `sysmon.py` — system and apps  (PRD F1, F2, F3, F4)
- [x] `Monitor()` class; `Monitor.snapshot()` returns
  `{"cpu": float, "ram": float, "ram_used_gb": float, "ram_total_gb": float, "apps": [App]}`
  where `App = {"name": str, "pids": [int], "ram_mb": float, "cpu": float, "idle_min": float}`. Apps are sorted by `ram_mb` descending.
- [x] Grouping: processes are grouped by display name (exe name without `.exe`, title-cased if it's lowercase: `chrome` → `Chrome`, `Cursor` stays). Child processes of a known heavy app (`HEAVY_APPS` list: Cursor, Kiro, Chrome, Notion, Code, Docker Desktop, msedge, Slack, Discord) count toward the parent app, e.g. `node.exe` under Cursor.
- [x] Hidden: `System`, `Idle`, `svchost`, `Registry`, `smss`, `csrss`, `wininit`, `services`, `lsass`, `winlogon`, `dwm`, `explorer`, `MsMpEng`, `fontdrvhost`, `Memory Compression`, and the panel's own process.
- [x] CPU % is per app, normalised to 0–100 of the whole machine. It's non-blocking: it uses psutil's interval-less `cpu_percent` between snapshots.
- [x] `idle_min`: how many minutes the app has stayed under 1% CPU without a break (tracked across snapshots).
- [x] `close_app(pids, timeout=3) -> bool`: terminate, wait, kill the survivors. Missing or denied processes don't raise.
- [x] `Pressure(threshold=85, hold_s=10, cooldown_s=300)`: `.update(ram_pct, now) -> bool` returns True once when RAM has stayed ≥ threshold for hold_s, and not again until cooldown_s has passed.
- [x] `pick_suggestion(apps) -> App|None`: the idle (≥ 10 min) app with the most RAM, otherwise the app with the most RAM.
- [x] `new_heavy_apps(prev_names: set, apps) -> list[str]`: heavy apps present now that weren't in `prev_names`.
- [x] `test_sysmon.py`: Pressure timing and cooldown, pick_suggestion, new_heavy_apps, a snapshot with a real shape check, close_app on a `python -c "sleep"` child it spawns itself.

### T2 · `hook.py` + `agents.py` — Claude Code agent status  (PRD F5)
- [x] State folder: `os.environ.get("DESK_BUDDY_HOME", ~/.desk-buddy)` + `/agents/`.
- [x] `hook.py` reads the hook JSON from stdin and writes `<session_id>.json` atomically (write temp, then `os.replace`):
  `{"session_id","project","state","action","todo_done","todo_total","todo_current","updated"}`
  - `project` = basename of `cwd`.
  - `UserPromptSubmit` → state `working`, action `Thinking…`.
  - `PreToolUse` → state `working`, action from the tool: Edit/Write/MultiEdit/NotebookEdit → `Editing <file name>`; Read → `Reading <file name>`; Bash → `Running <first 40 chars of command>`; Grep/Glob → `Searching code`; WebFetch/WebSearch → `Browsing the web`; Task/Agent → `Running a subagent`; anything else → `Using <tool>`.
  - `TodoWrite` tool_input.todos → `todo_done` = number completed, `todo_total` = length, `todo_current` = the `activeForm` (or `content`) of the in_progress item. Earlier todo values are kept on other events.
  - `Stop` → state `waiting`, action `Done — waiting for you`.
  - `Notification` → state `needs_you`, action = the notification `message` (first 60 chars).
  - `SessionEnd` → delete the file.
- [x] `hook.py` must **never** break Claude Code: wrap everything, always exit 0, print nothing to stdout, finish in < 200 ms.
- [x] `agents.py`: `load_agents(home=None, now=None, stale_min=30) -> list[dict]` reads every file, deletes and skips files whose `updated` is older than stale_min, skips corrupt files, and sorts with `needs_you` first, then `working`, then `waiting`, most recent first within each.
- [x] `test_agents.py`: runs `hook.py` as a subprocess with sample JSON for each event (temp `DESK_BUDDY_HOME`), then checks files and `load_agents` ordering, staleness, corrupt-file tolerance, and that bad stdin still exits 0.

### T3 · `notion.py` — today's tasks  (PRD F6)
- [x] `load_config(home=None) -> dict`: reads `NOTION_TOKEN` / `NOTION_DB_ID` from the env, otherwise from `<home>/config.json` (`{"notion_token","notion_db_id"}`); returns `{}` if neither is set.
- [x] `fetch_today(token, db_id, today=None, opener=urllib.request.urlopen) -> list[{"title","url"}]`: gets the DB schema, finds the first `date` property, the `title` property, and a done property (checkbox, or status/select named Done/Complete). Then queries the DB for items with date ≤ today that aren't done, and returns at most 5. API version header `2022-06-28`.
- [x] Any error (network, auth, schema) → returns `[]`, never raises.
- [x] `test_notion.py`: a fake `opener` returning canned JSON covers the happy path, a missing date property, an HTTP error, and config loading from env vs file.

### T4 · `install.py` — autostart and hooks  (PRD §9.2)
- [x] `install(settings_path=~/.claude/settings.json, startup_dir=<shell:startup>, python_exe=sys.executable)`:
  - Merges hook entries for `UserPromptSubmit`, `PreToolUse` (matcher `*`), `Stop`, `Notification`, `SessionEnd` that run `"<python.exe>" "<abs path>/hook.py"`. It keeps every existing key and existing hook, is idempotent (running it twice adds no duplicates), and writes a `settings.json.bak` backup first. Invalid JSON → abort without writing.
  - Creates `Desk Buddy.lnk` in the Startup folder pointing to `pythonw.exe` + `desk_buddy.pyw` (via PowerShell `WScript.Shell`), with the working dir set to the project folder.
- [x] `uninstall(...)` removes only the entries it added, plus the shortcut.
- [x] CLI: `python install.py` / `python install.py --uninstall`.
- [x] `test_install.py`: temp settings with existing user hooks and keys covers merge, idempotency, uninstall restoring the original content, and invalid JSON being left untouched. The shortcut is created in a temp dir and must exist.

## Wave 2 — UI (after wave 1 passes)

### T5 · `desk_buddy.pyw` — the panel  (PRD §4, F1–F6)
- [x] Frameless (`overrideredirect`), `-topmost`, about 340 px wide, top-right by default. Draggable by the header; position saved to `<home>/state.json`.
- [x] Dark rounded cards (canvas), a coloured mascot face per agent card (it blinks or bobs while `working`), lime progress bar, amber ⚠ for `needs_you`.
- [x] Sections: header (`● Desk Buddy`, 🔇, ^ collapse, ✕ quit) → System bars → Apps (top 6 + "+N more" toggle, ✕ with inline "Close X? ✓ ✗") → Claude Code agents (hidden when there are none) → Notion · Today (hidden when there's no config).
- [x] When collapsed: only the header, showing `CPU 68% · RAM 81%`.
- [x] Refresh: system/apps/agents every 2 s via `after()`. Notion every 5 min on a background thread. The UI thread never blocks.
- [x] Pressure banner (F3) with a [Close] button and an optional `winsound` beep; a new-app toast (F4) that hides after 4 s.
- [x] Single instance: a second launch exits (lock or socket on 127.0.0.1).
- [x] `test_ui.py`: builds the window with `--selftest` (renders a few frames with fake data, then destroys itself), runs it, and checks the process RSS is < 50 MB.

## Wave 3 — integration
### T6 · Integration test
- [x] All `test_*.py` files pass together.
- [x] Launch `desk_buddy.pyw` for 10 s: no exceptions, RSS < 50 MB, CPU < 2%.
- [x] Pipe sample hook events through `hook.py`, and the agent card data shows up via `load_agents`.
- [x] `README.md`: install, uninstall, Notion config, troubleshooting.

## After the harness (orchestrator, i.e. main session)
- [x] Review the diff, run `python install.py` for real (it backs up settings.json), launch the panel, and show Yash.

---

# v2 tasks (PRD "v2" section)

## Wave 1 — modules (parallel; each owns only its files)

### T7 · `winui.py` — tray, notifications, hotkey, fullscreen  (V2, V3, V4)
- [x] `Tray(on_toggle, on_quit, tooltip="Desk Buddy")`: `.start()` runs a hidden pywin32 window and message loop on a daemon thread. Tray icon: a small lime dot is fine (build an HICON in memory or use a stock icon; no image files required). Left-click → `on_toggle()`; right-click menu: "Show / Hide", "Quit" → `on_quit()`. `.notify(title, msg)` shows a Windows balloon/toast through the same icon. `.stop()` removes the icon.
- [x] The global hotkey **Win+Shift+D** (`RegisterHotKey` on the same thread/window) → `on_toggle()`. If registration fails (already taken), carry on silently.
- [x] Callbacks run on the win32 thread. Document that the caller must marshal to tk (e.g. a `queue.Queue` polled by `after`).
- [x] `fullscreen_active() -> bool`: True when the foreground window covers its whole monitor and isn't the desktop/shell (`Progman`, `WorkerW`, `Shell_TrayWnd`).
- [x] Any pywin32 import or runtime failure → the module still imports, Tray becomes a no-op, and `fullscreen_active()` returns False.
- [x] `test_winui.py`: start a Tray, notify, stop (no exceptions, thread exits); `fullscreen_active()` returns a bool; a no-op fallback when `win32gui` can't be imported (simulate via `sys.modules` patch).

### T8 · `sysmon.py` additions — pause, leaks, rules  (V1, V5, V8)
- [x] `suspend_app(pids) -> bool`, `resume_app(pids) -> bool` (psutil suspend/resume; missing or denied processes don't raise).
- [x] `PauseBook(home=None)`: saves paused apps `{name: [pids]}` to `<home>/paused.json`. `.pause(app)`, `.resume(name)`, `.is_paused(name)`, `.resume_all()`. On construction, any leftover entries from a crash are **resumed and cleared**.
- [x] `Monitor.snapshot()` App dicts gain `"paused": bool` (from the PauseBook passed via `Monitor(pausebook=None)`). Paused apps aren't counted toward idle-based suggestions.
- [x] `Monitor.leaks(min_growth_mb=1000, window_min=30) -> [{"name","growth_mb","minutes"}]` from per-app RAM history kept in Monitor (bounded memory: at most about 1 sample per minute, 60 per app).
- [x] `evaluate_rules(rules, snap, now, fired) -> [{"app": App, "action": "pause"|"close", "rule": dict}]`. Rule keys: `if_ram_over` (system RAM %), `app` (name), optional `idle_min`. The same rule+app fires at most once per 10 min (`fired` dict, mutated). Invalid rules are skipped.
- [x] Existing T1 behaviour and `test_sysmon.py` keep passing. New checks go in `test_sysmon.py`: suspend/resume a spawned child (psutil status shows stopped, then running), PauseBook crash recovery, leaks with fake history, evaluate_rules cases.

### T9 · `statusline.py` + `usage.py` + `install.py` updates  (V6, V7, V10)
- [x] `statusline.py`: reads the statusLine JSON from stdin and atomically writes `<home>/usage/<session_id>.json` = `{"session_id","model","ctx_pct","cost_usd","five_hour":{"pct","resets_at"}|null,"seven_day":{...}|null,"updated"}`. Prints ONE short line, e.g. `Opus · ctx 23% · 5h 42% · wk 18%` (skip missing parts). It never raises, always exits 0, and is fast (< 150 ms). Home is `DESK_BUDDY_HOME` or `~/.desk-buddy`.
- [x] `usage.py`: `load_usage(home=None, now=None) -> {"five_hour": {"pct","resets_at"}|None, "seven_day": ...|None, "sessions": {sid: {"model","ctx_pct","cost_usd"}}}`. Limits come from the most recently updated file that has them, and a window whose `resets_at` < now is dropped. Session files older than 30 min are removed; corrupt files are skipped. `fmt_reset(resets_at, now) -> "2h 10m"` / `"3d 4h"` / `"45m"`.
- [x] `install.py`: add `statusLine` = `{"type":"command","command":"\"<python>\" \"<abs>/statusline.py\"","padding":0}` **only if no statusLine exists**; uninstall removes it only if it's ours. Also create/remove a **Start Menu** shortcut `Desk Buddy.lnk` (in `%APPDATA%\Microsoft\Windows\Start Menu\Programs`), same target as the Startup one. Keep existing install behaviour and idempotency.
- [x] `test_usage.py` (statusline subprocess with sample payloads incl. missing `rate_limits` and garbage stdin; load_usage expiry, staleness, corrupt files; fmt_reset). Extend `test_install.py`: statusLine added when absent, untouched when the user has their own, removed on uninstall; Start Menu shortcut in a temp dir.

### T10 · Docs and packaging  (V11)
- [x] `README.md` rewrite: one-line pitch; a screenshot placeholder `docs/screenshot.png` (filled in wave 3); features (short, scannable); install/uninstall; "If you closed it" (tray, Win+Shift+D, Start Menu); config.json reference (Notion, rules); a Mermaid architecture diagram (Claude Code hooks/statusLine → JSON files → panel; psutil → sysmon → panel; win32 tray); a **"How it was built"** section (PRD → TASKS → multi-agent harness: orchestrator, parallel workers, tester feedback loop) linking PRD.md and TASKS.md; privacy note (everything is local, nothing leaves the machine except optional Notion).
- [x] `build_exe.ps1`: PyInstaller one-folder build of `desk_buddy.pyw` (windowed) plus copies of hook.py/statusline.py. Comment at top: run `pip install pyinstaller` first. Don't run it.
- [x] `.gitignore` (`__pycache__/`, `build/`, `dist/`, `*.spec`, `*.bak`), `LICENSE` (MIT, "Yash Gurav", 2026).
- [x] `requirements.txt`: `psutil`, `pywin32`.

## Wave 2 — UI  (after wave 1)
### T11 · `desk_buddy.pyw` integration
- [x] Header ✕ → hide to tray (`withdraw`). Real quit only from the tray menu → resume all paused apps, stop the tray, destroy. Win+Shift+D and tray click toggle `withdraw`/`deiconify`. Win32 callbacks are marshalled via `queue.Queue` polled with `after`.
- [x] Usage pill in the header, left of the icons: `5h 42% · wk 18%`, small font, dim (amber ≥ 80, red ≥ 95). Hidden if there's no data. A click toggles a single line under the header: `5h resets in 2h 10m · week in 3d 4h`. Collapsed header: `CPU 68% · RAM 81% · 5h 42%`.
- [x] Apps: a dim ⏸ left of ✕ (no confirm, since it's reversible). Paused rows are dimmed with "paused" and a ▶ resume. The mouse wheel over the Apps card scrolls the expanded list (offset clamped); the "… not shown" line is gone.
- [x] Notifications via `Tray.notify`: an agent's state switching to `needs_you` (once per transition), the pressure warning, the leak warning.
- [x] Fullscreen: check every 2 s, `withdraw` while `fullscreen_active()`, restore afterwards, but only if the panel was visible before.
- [x] Leak banner (reuse the pressure banner style) and auto-rules (from `notion.load_config`-style `config.json` key `rules`, or extend the config loader inside the UI); a toast for every rule action.
- [x] Expanded agent card: a `model · ctx N% · $X.XX` line from `usage.load_usage()["sessions"][sid]` when present.
- [x] `--selftest` covers the new states (paused row, usage pill and reset line, expanded agent with ctx line, scrolled list) and still destroys itself. RSS < 50 MB. No tray left behind.

## Wave 3 — integration
### T12
- [x] All `test_*.py` pass. Launch the panel 10 s with a temp home and port: no crash, RSS < 50 MB, CPU < 2%, the tray icon is cleaned up on kill/quit.
- [x] `docs/screenshot.png`: render `--selftest`-style fake data (no real user processes or projects) and grab the window with Pillow `ImageGrab`.
