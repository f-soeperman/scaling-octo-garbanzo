# Project 3: Sandbox (Zandbak) Notifications

> Reference doc, read on demand — read it before changing this project's files. The always-loaded rules (privacy, ground rules, security) live in [`CLAUDE.md`](../CLAUDE.md); where the two differ, `CLAUDE.md` wins.

**Goal:** Daily Telegram notifications about opening, closing, or covering the sandbox, based on weather forecast and current state.

## Files
- `sandbox_notify.py` — weather logic + Telegram
- `sandbox_state.json` — current state (committed by Action after each run)
- `.github/workflows/sandbox-notify.yml` — scheduler + skip logic + manual dispatch

## State machine
Three states in `sandbox_state.json`:
- `open` — sandbox is aired out
- `dicht` — closed against cats, dry expected, will open tomorrow
- `afgedekt` — tarp on, rain expected

State updates automatically after each notification. Manual override via `workflow_dispatch` with `override_status` dropdown.

## Timing
Two crons in `Europe/Amsterdam` time: `08:00` (morning) and `19:00` (evening). GitHub Actions' native `timezone:` field handles DST automatically, so no UTC drift. The workflow itself decides `morning` vs `evening` based on the local hour (`< 12` → morning) — `sandbox_notify.py` does not contain its own skip-window logic.

## Rain threshold
≥30% probability OR ≥1mm expected.

## Relation to other projects
Fully independent — does not touch `soil_model.py`, `check_and_notify.py`, `daily-check.yml`, or `data.json`. Shares Telegram secrets only.
