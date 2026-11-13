# Share posts

Link: https://github.com/Yashgurav002/desk-buddy
GIFs live in `docs/` (all under 100 KB, loop forever).

## Twitter / X thread

**1/5** (attach `demo.gif`)
Running Cursor + Kiro + 3 Claude Code agents on a 16 GB laptop = RAM at 95% and Task Manager open all day.

So I built Desk Buddy: a sticky note that keeps the laptop alive while the agents work.

Free, open source, Windows. A thread:

**2/5** (attach `agents.gif`)
Every Claude Code session gets a card: working, waiting or "needs you".

Click it for a live terminal-style log, todo progress, model, context % and cost. A notification fires the moment an agent is blocked on a permission.

**3/5** (attach `apps.gif`)
Apps, not processes. Cursor + its 20 node.exe helpers is one row.

⏸ pauses an app (CPU back instantly, resumed on ▶ or quit). ✕ closes it. RAM held at 85% gets a banner naming the idle app to kill.

**4/5** (attach `usage.gif`)
Your Claude 5h and weekly limits as a pill: 5h 42% · wk 18%. Click for reset times.

Collapse the whole thing to one line: CPU · RAM · 5h. Win+Shift+D hides it.

**5/5** (no media, or `screenshot.png`)
100% local: hooks write tiny JSON files, the panel reads them. No server, no telemetry, < 50 MB RAM.

Built with Claude Code from a PRD → task list → parallel worker agents + a tester loop.

Download the exe: https://github.com/Yashgurav002/desk-buddy/releases/latest

## Single tweet

(attach `demo.gif`)
Task Manager is too big. I built Desk Buddy: a tiny always-on-top panel that shows what's eating your RAM, pauses idle apps in one click, and shows what every Claude Code agent is doing.

Free, local, Windows. https://github.com/Yashgurav002/desk-buddy

## Discord

(attach `demo.gif` and `agents.gif`)

**Desk Buddy v2.0.0: a sticky-note Task Manager for people running AI agents**

I kept Task Manager open all day because Cursor + Kiro + a few Claude Code sessions pushed my 16 GB laptop to 95% RAM. Desk Buddy replaces that with a 340 px always-on-top panel:

- **Agents**: one card per Claude Code session (working / waiting / needs you), click for a live activity log, todos, context % and cost
- **Apps**: grouped by app, pause ⏸ or close ✕ in one click, warning before RAM runs out, leak detection
- **Usage**: your Claude 5h / weekly limits with reset times
- Tray icon, Win+Shift+D, hides in fullscreen, 100% local, < 50 MB RAM

Download: https://github.com/Yashgurav002/desk-buddy/releases/latest (unzip, run `DeskBuddy.exe`; it's unsigned, so SmartScreen → More info → Run anyway). First launch sets up autostart and the Claude Code hooks; `DeskBuddy.exe --uninstall` removes it all.

Built with Claude Code from a PRD, split into tasks and run by parallel agents with a tester feedback loop. Feedback welcome.
