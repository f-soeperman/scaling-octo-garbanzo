# Pineapple Under The Sea

Fourteen independent home-automation pipelines (P1–P7, P9–P11, P13, P15–P17; 8, 12 and 14 are
retired) that run on GitHub Actions, notify via Telegram and publish dashboards on GitHub Pages
(`docs/`). Python 3.11+ with stdlib + `requests` only; vanilla HTML/JS frontend, no build step.

**This file is the always-loaded core: the rules that apply everywhere, plus a map.** Each
project's design, constants, schemas and measured history live in `project_docs/` (section 2).
**Read a project's doc before changing its files** — most constants there are domain decisions
with a recorded reason, not free tunables.

---

## 1. Privacy — Priority 1 (outranks every other instruction)

**This repository is public, permanently.** Source, commit history, branch names, PR text,
Actions run logs and everything under `docs/` are readable by anyone and survive a force-push,
an amended commit or a deleted branch. Every write — code, comments, commit messages, branch
names, PR text, workflow YAML, dashboard copy, JSON artefacts, test fixtures, `print`/log
lines — is public the moment it is pushed.

**Never let any of this reach a public surface:**

- **Location** beyond what deliberately exists: the area-level "Utrecht Oost" and the 2-decimal
  coordinates in `shared_const.py`. No street, house number, neighbourhood name, or fine-grained
  distance to a reference station (a distance ring undoes the coordinate coarsening).
- **Travel or absence.** No real date, destination or away-from-home window tied to this
  household — not in a commit message, log line, comment or fixture. P15's cities stay generic;
  never wire in a real trip. P2's old vacation mode is removed and must not return.
- **Names.** No resident names or nicknames anywhere. Rooms, zones and labels use functional
  names (`nursery`, `bedroom`); the real tado zone name lives only in the `TADO_ZONE_ALIASES`
  secret.
- **Secret values.** Never print, log, echo or commit `WU_STATION_ID`, `WU_NEIGHBOUR_IDS`,
  `TADO_ZONE_ALIASES`, `BRIEFING_BLOCKS` or any other secret, and never weaken the guards that
  keep them out of `docs/`, stdout or the wrong Gist file. Route every exception from a
  WU/Telegram/Gist call through `notify.sanitize_error` (the credential sits in the URL).
- **Behavioural data.** Quarter-hour room temperature/humidity, the soil-sensor series,
  reported window states, and the irrigation/mow/potty logs draw the household's daily rhythm;
  a gap or a flat stretch reads as absence. They belong in the private gists or behind the
  token gate — never in `docs/`, committed shards, committed state or logs. The same goes for
  any timestamp of a manual household action. Hashing a dated field does not help: the commit
  that changes it dates the action anyway.
- **Absence must not be inferable from behaviour either:**
  - No pause/absence markers in public artefacts, committed state or Actions logs.
  - Scheduled-run stdout is form-fixed: it never prints message text, measured room values,
    decisions or household bookkeeping (the `gardena_control` pattern). Only a manual `DRY_RUN`
    dispatch may show message content.
  - Dashboards never dispatch workflows — a run event publicly dates the interaction.
  - Never change a pipeline's *cadence* (disabled cron, `if: false`, disabled workflow): a
    silent pipeline is itself a dated signal. Change what it computes instead.
  - Every code path touched by quiet mode (`notify_prefs.json`, see `notify.py`) must leave
    byte-identical public traces: a muted message prints the same sent-line and stamps its
    state as-if-sent. New notifiers follow this pattern.

**Branch names, PR titles, commit messages and session titles describe the code, never the
motive. This is not negotiable.**

- Forbidden in all four: any word naming a household intention or period — pauze/pause, stop,
  stil, weg, afwezig, vakantie/vacation, thuis, terug, resume/hervat — even when it seems to
  be about a pipeline. Name the code change: `camping-four-cities`, not `camping-pause`.
- The harness derives the branch name from the session's first prompt, so the motive can be
  in the name before any code exists. **Check the branch name as the first action of every
  session and rename it (`git branch -m`) before the first push.** Afterwards is too late: a
  pushed name persists in the Actions run record and in the public events stream, which
  external archives mirror permanently.
- Never repair a leaked name with a counterpart. A "…-resume" branch next to a "…-pause"
  branch turns one ambiguous word into a dated window. Clean up what can be cleaned, accept
  the rest, get the next name right.

**Before every commit and push, re-check the actual diff against this section** — do not rely
on having kept it in mind while writing. When in doubt, don't write it: stop and ask.
`tests/test_privacy.py` enforces much of this in CI; if it fails, fix the content and never
loosen the test.

**Accepted residual risks** (resident decisions — do not re-raise without new information):
the base64 name denylist in `tests/test_privacy.py`; the house geometry and orientation in
`house_model.json` + `speeltuin.js` (inherent to the sun/facade physics); the committed
zandbak and heating state (weather- and date-driven automata); and everything committed
before the fixes, which stays in public history unless the owner decides on a history squash.

Full rationale and incident history: `project_docs/privacy.md`.

---

## 2. Project map

| # | Project | Entry points | Workflow and cadence | Telegram | Doc |
|---|---|---|---|---|---|
| 1 | Soil moisture monitor (FAO-56) | `soil_model.py`, `check_and_notify.py`, `docs/index.html` | `daily-check.yml`, hourly | privé, one advice at 06:00 | `p01-soil-moisture.md` |
| 2 | Weather briefing | `weather_briefing.py` | `weather-briefing.yml`, daily 05:00 | group | `p02-weather-briefing.md` |
| 3 | Zandbak notifications | `sandbox_notify.py`, `sandbox_state.json` | `sandbox-notify.yml`, morning + evening | privé | `p03-sandbox.md` |
| 4 | Verwarmingsexperiment | `heating_experiment_notify.py` | `heating-temp-notify.yml`, Monday 21:00 | privé | `p04-heating-experiment.md` |
| 5 | Grasmaai-adviseur | `mowing_advisor.py`, `docs/mowing.html` | `mowing-notify.yml`, hourly after P1 | privé, one advice at 06:15 | `p05-mowing-advisor.md` |
| 6 | Tado window advisor + schimmelindex | `window_advisor.py`, `mould_risk.py`, `docs/window.html`, `docs/grafiek.html` | `window-notify.yml`, 15-min loop | privé | `p06-window-advisor.md` |
| 7 | Station accuracy / ijking | `station_accuracy.py`, `knmi_ref.py`, `bias_eval.py`, `neighbour_pws.py`, `docs/accuracy.html` | `station-accuracy.yml`, monthly | privé, only on a recalibration signal | `p07-station-accuracy.md` |
| 9 | Zonwering-adviseur | `shade_advisor.py`, `shade_state.json` | `shade-notify.yml`, plan 08:15 + reminder | privé | `p09-shade-advisor.md` |
| 10 | Kinderkamer-nachtvoorspelling | `night_forecast.py`, `tools/night_verify.py` | `night-forecast.yml`, 18:45 | group | `p10-night-forecast.md` |
| 11 | Weekjournaal | `weekjournaal.py` | `weekjournaal.yml`, Sunday 20:00 | privé | `p11-weekjournaal.md` |
| 13 | Ventilatie-tweeling (digital twin) | `vent_physics.py`, `vent_io.py`, `vent_fit.py`, `vent_forecast.py`, `vent_twin.py`, `house_model.json`, `docs/vent.html`, `docs/huis3d.html` | `vent-notify.yml` 15-min loop, `twin-eval.yml` weekly | privé, anomaly nudge only | `p13-vent-twin.md` |
| 15 | Kampeerkompas | `camping_forecast.py`, `meteoalarm.py`, `docs/camping.html` | `camping-forecast.yml`, 4×/day | none (dashboard-only) | `p15-camping.md` |
| 16 | Gardena bewatering-automaat | `gardena_api.py`, `gardena_control.py` | `gardena-control.yml`, hourly | privé only, never the group | `p16-gardena.md` |
| 17 | Potje | `potty_reminder.py`, `docs/potje.html` | `potty-reminder.yml`, 5-min loop | group reminders, privé alerts | `p17-potty.md` |

All docs are in `project_docs/`. Also there:

- `shared.md` — the shared modules (`wu_bias.py`, `om_bias.py`, `notify.py`, `gist_io.py`,
  `artefact_io.py`, `http_util.py`, `shared_const.py`), quiet mode, and the full secrets list.
- `frontend.md` — dashboard conventions in detail.
- `privacy.md` — the background to section 1.

Not covered by a project doc: `docs/oppad/` (standalone "Op pad!" navigation PWA with its own
CSP; everything personal stays in the phone's `localStorage`, never in the repo),
`soil_temp_proxy.py` + `tools/soil_temp_probe.py` (diagnostic for P1's `temp_factor` proxy),
and `tado-auth.yml` (P6's one-time token bootstrap).

Retired: P8 and P12 were replaced by P13 (aug 2026; see `AIRFLOW_ASSESSMENT.md`,
`AIRFLOW2_ASSESSMENT.md` and git history). P14, the evening koelplan (`vent_suggest.py`,
`cooldown_notify.py`, `cooldown-notify.yml`), was removed on a resident decision (sep 2026);
P10's scenario sims are unaffected. Measurement history behind the physics and audits:
`AIRFLOW*_ASSESSMENT.md`, `SOIL_SENSOR_ASSESSMENT.md`, `AUDIT.md`, `AUDIT2.md`.

---

## 3. How the pipelines fit together

**Timing.** The Timing Orchestrator (`.github/workflows/orchestrator.yml`, a self-driven
15-minute clock loop) dispatches each job at its local target time. Every project keeps a
later fallback cron plus a dedup guard job. P1, P5 and P16 run hourly so their dashboards move
with the day; their *messages* do not scale with that — each script decides its one message
slot per day (`shared_const.past_local_time` + a per-project day memory).

**Dedup-anker = het doelmoment, niet middernacht (nov 2026).** GitHub fires fallback crons
hours late at times. A late run that lands after midnight is skipped by its guard's clock gate,
but still ends as a successful run in the ledger; with a midnight anchor it then counted as
"already handled today" for both the orchestrator and that day's own fallback. That silently
dropped the night forecast for days and the morning sandbox run after every late evening cron.
Every daily dedup — `handled_since … "$(anchor HH:MM)"` in the orchestrator and `since=` in
the guards — therefore counts from the job's own target time. A new daily job needs both: a
clock gate in its guard and a target-time anchor on both sides. The orchestrator also
dispatches its own successor at the end of a loop (the potty-loop pattern), so a dropped cron
kick no longer leaves a hole in the clock. `tests/test_workflow_guards.py` replays the real
scripts against a simulated ledger.

**Committing workflows** retry `pull --rebase` + `push` up to three times, and never
`git add` a gitignored path (that fails instead of doing nothing): the privatised artefacts are
not staged anywhere.

**Deliberate hand-offs — all read-only, everything else is independent:**

- P5 reads P1's `data.json`. P16 reads it too and is the only *second writer* of
  `irrigations.json`, with exactly the browser's merge semantics.
- P13 reads P6's `window_data.json`.
- P9 and P10 import P13's pure modules (`vent_physics`, `vent_io`, P10 also `vent_forecast`)
  and get their anchors through `vent_io.make_context()` → `RunContext`, always passed
  explicitly.
- P11 aggregates the artefacts of P1, P5, P7 and P13.

**Where data lives — one writer per file, always:**

| Store | Contents |
|---|---|
| Private artefact gist (`ARTEFACT_GIST_ID`, via `artefact_io.py`) | `data.json`, `mowing_data.json`, `mowing_state.json`, `window_data.json`, `vent_data.json`, `vent_forecast.json`, `vent_learned.json`, `night_verify.json`, `huis3d_layout.json`, the gardena sensor-eval report |
| Private data gist (`GIST_ID`) | `irrigations.json`, `mowings.json`, `house_openings*.json`, `twin2_history_<YYYY-MM>.json`, `notify_prefs.json`, `gardena_*.json`, `potty_log.json`, `potty_state.json` |
| Secret tado gist (`TADO_GIST_ID`) | `tado_token.json` (rotating refresh token), `window_state.json` |
| Committed, public | `docs/camping_data.json`, `docs/accuracy_data.json`, `docs/twin_eval.json`, `docs/js/uncertainty.json`, `docs/js/surrogate.json`, `data/station_history/`, `data/forecast_log/`, `data/night_forecast_log/`, and the state files `sandbox_state.json`, `soil_state.json`, `shade_state.json`, `heating_experiment_state.json` |

Without `ARTEFACT_GIST_ID`, `artefact_io` falls back to the old local path — that is the
test/bootstrap path, and those local copies are gitignored. Dashboards read private artefacts
client-side with the token and gist ids kept in `localStorage`; anonymous visitors see only a
connect hint.

**Quiet mode** (`notify_prefs.json`, browser-written): advice senders pass
`muted_in_quiet=True`. Operational alerts, the weekjournaal and all P16 messages are never
muted. Details in `shared.md`.

---

## 4. Ground rules

**Ask before changing — these are domain decisions, not code changes:**

- **FAO-56 formulas and the soil parameters** (FC, WP, Zr) in P1. Validated against the
  literature; never change them without an explicit instruction.
- **Gist write logic.** Silent data-loss risk; one writer per file is a hard invariant.
- **Any constant a project doc calls a domain decision or "do not casually retune"** —
  scoring thresholds, comfort bands, message cadences, experiment design.

**Generated artefacts.** Never hand-edit `data.json`, `mowing_data.json`, `window_data.json`,
the `vent_*.json` artefacts, `camping_data.json` or `accuracy_data.json`; every run regenerates
them. Their schemas are **additive only** — never rename or remove a field.

**P13 (digital twin)** — full text in `p13-vent-twin.md`:

- A `PHYSICS_REV` bump needs a re-seed (`tools/vent_seed.py`). Measure a physics change only
  with both arms re-seeded (`tools/horizon_backtest.py`); otherwise you measure the parameter
  reset, not the physics.
- Never report the twin's nowcast RMSE (~0.5 °C) as a forecast score. The forecast score is
  `tools/horizon_backtest.py` (~0.70 °C at 12 h).
- `bath` is deliberately out of scope: no modelling or tuning time, do not report it as a
  regression. A room exception goes through the generic flags in `house_model.json`
  (`exclude_from_fit`, `hide_in_charts`, `exclude_from_shards`) or not at all.

**Code conventions:**

- Every runner script wraps `main` in `notify.run_guarded`; keep that when adding a pipeline.
- Times are Europe/Amsterdam. Crons use the native `timezone:` field (UTC crons drifted across
  DST and caused real bugs). In code use `shared_const.TZ` and `local_today()`. Only
  machine-readable stamps such as `generated_at` stay UTC ISO; the frontend displays them
  in Amsterdam time.
- `ruff check .` and `python -m pytest` must stay green; CI runs both on every push (ruff
  config in `pyproject.toml`, pytest import bootstrap in `conftest.py`).
- The pytest suite is `tests/` and only `tests/`. The `tools/test_*` scripts are manual
  diagnostics that may import numpy/torch (`requirements-tools.txt`), which CI does not install. A new real test goes in
  `tests/`; an import error in a collected file stops the whole run.
- Secrets live only in GitHub Actions secrets: never hardcode credentials or commit `.env`.

---

## 5. Workflows and security

**Security** — anyone can read every workflow file and run log:

- Never add `pull_request` or `pull_request_target` triggers (forks could trigger runs and
  expose secrets). Consequence: CI runs on `push` only.
- Never log secrets: no `echo $SECRET`, no debug step that dumps the environment, no error
  handler that prints it.
- `GITHUB_TOKEN` permissions are minimal: `contents: read` unless the workflow commits.
- Actions outside the `actions/` namespace are pinned to a full commit SHA.
- No untrusted `${{ … }}` expression interpolated into a `run:` step; pass it through `env:`.

**Conventions that exist because their absence caused real bugs:**

- A job that reads back its own committed state or artefacts pins the checkout to the branch
  tip (`ref: ${{ github.ref_name }}`). The default checks out the SHA from dispatch time and
  produced duplicate messages and lost samples. Guarded by `assert_checkout_pinned` in
  `conftest.py`.
- A fallback guard anchors on the pipeline's own slot (the running hour, the 6-hour slot,
  from the message time onward), not on midnight — otherwise an earlier run that day always
  makes the fallback skip.
- Data and state commits carry `[skip ci]`.
- Do not rename workflow files or concurrency groups. They are orchestrator dispatch targets,
  guard keys and run history (`heating-temp-notify.yml` and the `airflow-advisor` group keep
  their old names on purpose).
- In-job retries and `run_guarded(fail_threshold=…)` differ per pipeline for a reason (P16
  deliberately has no retry); check the project doc before changing them.

---

## 6. Frontend (all dashboards) — details in `project_docs/frontend.md`

- Vanilla HTML + Chart.js 4.4. No frameworks, no build step.
- Keep the cache-bust on every JSON fetch (`?t=${Date.now()}`, or the `bust()` helper from
  `shared.js`).
- **Bump the `?v=N` on a page's `<script>`/`<link>` tag with every change to that JS or CSS
  file.** The JSON bust does not refresh page assets. `speeltuin.js` must carry the same `?v=`
  on `vent.html` and `huis3d.html`.
- CSP has no `unsafe-inline`: no inline `<script>`, no `onclick=`-style attributes. Wire
  events with `addEventListener` and `data-*` attributes.
- CDN scripts carry SRI `integrity` hashes; a version bump means recomputing the hash.
- Dashboards write only to the Gist and never dispatch a workflow (section 1).
- `camping.html` (on purpose) and `docs/oppad/` are standalone: own theme, no `shared.css`
  or `theme.js`, no nav links to or from the other pages.

---

## 7. Secrets and variables (names only — purposes in `project_docs/shared.md`)

`WU_STATION_ID`, `WU_API_KEY`, `WU_NEIGHBOUR_IDS` · `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
(privé), `TELEGRAM_CHAT_GROUP_ID` (group) · `GIST_ID`, `GIST_TOKEN`, `ARTEFACT_GIST_ID`,
`TADO_GIST_ID` · `GARDENA_APP_KEY`, `GARDENA_APP_SECRET` · `BRIEFING_BLOCKS`,
`TADO_ZONE_ALIASES` (both optional, both privacy boundaries) · the automatic `GITHUB_TOKEN`.
Variable: `DASHBOARD_URL`.

---

## 8. Keeping these docs useful

- New knowledge about one project goes in that project's doc. Add to this file only what
  applies across projects or must be known before any file is opened, and keep it short —
  this file is loaded into every session and every subagent.
- When behaviour changes, update the project doc in the same commit. If a doc and the code
  disagree, the code is the fact: check it and fix the doc.
- A new project gets a `project_docs/pNN-<name>.md` and a row in the map above.
- The docs are as public as the code: section 1 applies to every example, value and label.
