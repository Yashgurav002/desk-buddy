# Desk Buddy — PRD (v1)

A small panel that stays on top in the top-right corner of the screen. It shows what's using the laptop's resources, lets you close heavy apps in one click, and shows what each Claude Code agent is doing. It replaces keeping Task Manager open.

Visual reference: the "Agent Huddle" Instagram reel (dark rounded cards, coloured mascot icon, title, subtitle, "3/5 step" text and a lime progress bar, ✕ per row). We use the style, not a copy of it.

## 1. Problem
- The laptop has 15.7 GB RAM. With Cursor and Kiro open together, CPU and RAM reach about 95%.
- Task Manager has to stay open all the time to find and close the heavy app. It lists processes, not apps, so one Cursor shows up as 20+ rows.
- Several Claude Code sessions run at once, and the only way to see which one is working, finished or waiting for input is to switch between terminals.

## 2. Goals
1. One look shows: total CPU/RAM, which **apps** are heavy, and what each Claude Code agent is doing.
2. One click closes a whole app, with all of its processes.
3. A warning before the machine chokes, not after.
4. The panel stays light: **< 50 MB RAM, < 1% CPU** when idle.

## 3. Non-goals (v1)
- Cursor or Kiro agent status (Claude Code only, as decided by Yash).
- Graphs or history, network/disk/GPU stats.
- Installer, auto-update, settings screen.

## 4. Layout (top-right, about 340 px wide, frameless, always on top)

```
● Desk Buddy                     [🔇] [^] [✕]
┌ System ───────────────────────────────────┐
│ CPU  ███████░░░  68%   RAM ████████░ 81%  │
└───────────────────────────────────────────┘
┌ Apps ─────────────────────────────────────┐
│ [■] Cursor        4.2 GB · 12% CPU     ✕  │
│ [■] Kiro          3.1 GB · idle 20m    ✕  │
│ [■] Chrome        2.4 GB · 3%          ✕  │
│   …top 6, rest collapsed                  │
└───────────────────────────────────────────┘
┌ Claude Code agents (2) ───────────────────┐
│ [face] portfolio-site                 ⧉   │
│        Editing Header.tsx                 │
│        3/5 Build hero section             │
│        ██████████░░░░░░                   │
│ [face] weather-bot         ⚠ needs you    │
│        Waiting for permission: Bash       │
└───────────────────────────────────────────┘
┌ Notion · Today ───────────────────────────┐
│ ☐ Send portfolio to recruiter             │
│ ☐ Review PR #42                           │
└───────────────────────────────────────────┘
```
- `^` collapses the panel to just the header line (CPU/RAM % in the title).
- The window can be dragged by its header, and it remembers where you left it.
- Dark theme, rounded cards, a coloured mascot per row (drawn on a canvas, no image files), lime progress bar.

## 5. Features

### F1. System bar
- Total CPU % and RAM % (used / total GB), refreshed every 2 s.
- The bar turns amber at ≥ 80% and red at ≥ 90%.

### F2. Apps (grouped)
- Processes are grouped by app (Cursor = Cursor.exe plus its children, and so on). Each row shows the summed RAM and CPU %.
- The top 6 apps by RAM are shown; "+N more" expands the rest.
- System processes are hidden (svchost, System, explorer, Defender, the panel itself).
- **✕ closes the whole app:** first a graceful terminate, then a force-kill after 3 s if it's still alive. Clicking ✕ asks inline ("Close Cursor? ✓ ✗") so a misclick can't lose unsaved work.
- An "idle Xm" label appears when an app has used < 1% CPU for 10+ minutes.

### F3. Pressure warning
- When RAM stays ≥ 85% for 10 s, the panel flashes and shows a banner: "RAM 88% — Kiro idle 20m using 3.1 GB. Close it?" with a [Close] button.
- The suggested app is the idle app using the most RAM, or the largest app if none is idle.
- Optional sound (the 🔇 toggle). The warning won't repeat for 5 minutes after it's dismissed.

### F4. New heavy app popup
- When a known heavy app starts (Cursor, Kiro, Chrome, Notion, Docker; the list sits at the top of the script), a toast appears: "Kiro opened — RAM now 78%". It disappears after 4 s.

### F5. Claude Code agents
- Data comes from Claude Code **hooks**, configured in `~/.claude/settings.json`. Each hook runs `hook.py`, which writes one small JSON file per session to `~/.desk-buddy/agents/<session_id>.json`. The panel reads that folder every 2 s.
- Card fields:
  - **Title:** the project folder name (from `cwd`).
  - **Subtitle:** the current action, from the tool used, e.g. "Editing Header.tsx", "Running npm test", "Searching code", "Thinking…".
  - **Progress `n/m step`:** taken from Claude's todo list (TodoWrite / task tools). Hidden when the session has no todo list.
  - **State:** working (animated face), done / waiting for you (`Stop`), needs permission (`Notification`, ⚠ amber).
- Hook events: `UserPromptSubmit` (working), `PreToolUse` (action and todos), `Stop` (waiting), `Notification` (needs you), `SessionEnd` (remove the card).
- Cards with no update for 30 minutes are removed automatically (in case the session crashed).
- ~~⧉ brings that terminal window to the front~~ (moved to v2, see §9).
- ✕ hides the card. It does not stop the agent.

### F6. Notion · Today (optional)
- Only shown if `NOTION_TOKEN` and `NOTION_DB_ID` are set (read from env or `~/.desk-buddy/config.json`).
- Lists up to 5 not-done items due today or overdue from one Notion database. Clicking an item opens it in the browser.
- Refreshed every 5 minutes. If it fails, the section is hidden instead of crashing.

## 6. Tech
- **Python 3.11 + tkinter + psutil.** All three are already on this laptop, so nothing new to install.
- Files: `desk_buddy.pyw` (the panel; `.pyw` means no console window), `hook.py` (the Claude Code hook), `README.md` (how to run it).
- Notion uses `urllib` from the standard library; no SDK.
- Autostart: an optional shortcut in `shell:startup`.
- Why not Electron or Tauri: a memory monitor that uses 300 MB defeats its own purpose.

## 7. Success criteria
- With Cursor and Kiro open, the user can close one from the panel in **under 2 clicks** without opening Task Manager.
- The panel itself uses < 50 MB RAM.
- A Claude Code session's card updates within 3 s of it starting a tool, and shows "needs you" within 3 s of a permission prompt.

## 8. Build phases
1. **v1a:** System bar, grouped apps, close-with-confirm, collapse, drag. (Testable on its own.)
2. **v1b:** Claude Code hook and agent cards.
3. **v1c:** Pressure warning and new-app toast.
4. **v1d:** Notion section (needs the token from Yash).

## 9. Decisions (2026-11-13)
1. Name: **Desk Buddy**, approved.
2. Autostart at login: **yes**. `install.py` adds a Startup shortcut.
3. Notion database: not chosen yet. The section is built now but stays hidden until `~/.desk-buddy/config.json` has a token and database id.
4. ⧉ "focus terminal" is **moved to v2**. The hooks don't reliably say which terminal window a session belongs to.
5. Build method: a multi-agent harness. The orchestrator (a workflow script) runs one worker agent per task in parallel. A tester agent checks each worker's output, and failures go back to that worker, up to 3 rounds. The UI is built after the modules are done, then an integration test runs. Task tracking lives in `TASKS.md`.

## 10. Module layout (the contract between the parallel agents)
| File | Owner task | Purpose |
|---|---|---|
| `sysmon.py` | T1 | CPU/RAM, grouped apps, close app, idle tracking, pressure warning, new-app detection |
| `hook.py` + `agents.py` | T2 | Claude Code hook (writes state) and the reader for the panel |
| `notion.py` | T3 | Today's Notion tasks (optional) |
| `install.py` | T4 | Merge hooks into `~/.claude/settings.json`, Startup shortcut, uninstall |
| `desk_buddy.pyw` | T5 | tkinter panel that uses all of the above |
| `test_*.py` | each task | Plain `assert` self-checks, run with `python test_x.py` |

---

# v2 (2026-11-13)

**Design rule: not overwhelming.** The default view looks almost the same as v1. Every new thing is either one small pill, one dim icon, or hidden until you click or until it matters. Anything rules-based is off by default and only configured in `config.json`.

## v2 features
| # | Feature | What the user sees |
|---|---|---|
| V1 | **Pause instead of close** | A dim ⏸ next to each app's ✕. Paused apps show dimmed, labelled "paused", with ▶ to resume. They're resumed automatically when Desk Buddy quits, and on its next start if it crashed (pids saved in `~/.desk-buddy/paused.json`). |
| V2 | **Tray icon and hotkey** | The header ✕ now hides to the tray instead of quitting. A tray icon near the clock: left-click shows or hides the panel, right-click gives Show/Hide and Quit. **Win+Shift+D** shows or hides it from anywhere. |
| V3 | **Windows notification** | When an agent switches to "needs you", or a RAM warning fires, a Windows notification appears (once per event). |
| V4 | **Auto-hide in fullscreen** | The panel hides while a fullscreen app (video, game, slides) is in front, and comes back after. |
| V5 | **Leak warning** | An app that grew ≥ 1 GB over 30 min gets the existing amber banner: "Chrome +1.2 GB in 30 min". Once per app per hour. |
| V6 | **Claude usage limits** | A small pill in the header: `5h 42% · wk 18%` (amber ≥ 80%, red ≥ 95%). Clicking it shows one line with the reset times. When the panel is collapsed, the header shows `CPU · RAM · 5h`. |
| V7 | **Context and cost per agent** | An expanded agent card shows `Opus · ctx 23% · $0.42` above its log. |
| V8 | **Auto-rules (opt-in)** | `config.json` → `"rules": [{"if_ram_over": 90, "app": "Kiro", "idle_min": 30, "action": "pause"}]`. When a rule fires, a toast explains it. No rules unless the user adds them. |
| V9 | **Scrolling app list** | The mouse wheel over the expanded Apps list scrolls through it. Nothing is cut off. |
| V10 | **Start Menu entry** | Type "Desk Buddy" in Start to relaunch it after quitting. |
| V11 | **Portfolio** | README with a screenshot, an architecture diagram, how it was built (PRD → TASKS → multi-agent harness), `build_exe.ps1` (PyInstaller, run at release time), `.gitignore`, MIT license. |

## Usage data source (V6, V7)
Claude Code sends its **statusLine** command a JSON payload with `rate_limits.five_hour/seven_day.{used_percentage,resets_at}`, `context_window.used_percentage` and `cost.total_cost_usd` (docs: code.claude.com/docs/en/statusline). `statusline.py` saves this to `~/.desk-buddy/usage/<session_id>.json` and prints a short line for the terminal. `install.py` sets `statusLine` only when none is configured; uninstall removes only its own entry. `rate_limits` only appears on Pro/Max plans and after the first response, so the pill hides when there's no data.

## Win32 (V2–V4)
Uses `pywin32`, which is already installed (Shell_NotifyIcon, RegisterHotKey, GetForegroundWindow). No new runtime dependencies.

## Out of scope
Jump to an agent's terminal, Notion setup (waiting on a database), building or publishing the .exe.
