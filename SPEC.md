# falcon-screener — Component Spec

_Spec v1 · 2026-06-14 · living doc._

## Purpose
Multi-profile stock screening service — surfaces candidate symbols (gappers, movers, setups)
for game plans and the strategy/trading pipeline.

## Responsibilities (`src/falcon_screener/`)
- **multi_screener.py** — orchestrates screening across multiple profiles (entry: `falcon-screener`).
- **profile_manager.py** / **profile_templates.py** — named screen profiles (CRUD, templates,
  import/export); backs the dashboard's `/api/screener/profiles*` endpoints.
- **finviz_csv_screener.py** — Finviz Elite screener data (`FINVIZ_API_KEY`).
- **ai_stock_screener.py** — LLM-assisted candidate ranking/selection.
- **feedback_loop.py** — incorporate outcomes back into screen tuning.
- **daily_report.py** — scheduled report (entry: `falcon-daily-report`).
- **yaml_serializer.py** — profile persistence.

## Interfaces
- Console scripts: `falcon-screener`, `falcon-daily-report`.
- Consumed by the dashboard (screener profile endpoints) and game-plan workflows.

## Dependencies
`falcon-core` (DB), Finviz Elite, optionally Polygon/Massive for price context, `anthropic`
(AI screener).

The image installs `falcon-core[data-sync]` (boto3+pyarrow for Massive S3 flat-file reads) plus
`falcon-trader` (provides `falcon_trader.intraday_scanner`). This is deliberate: the screener
image is also the **intraday-scan WORKER** for falcon-trader #10 — it is the only built image that
carries boto3 (flat-file tier) AND `falcon_screener.profile_manager.ProfileManager` (persist) AND
`falcon_trader.intraday_scanner` in one process, which `intraday_scanner.persist_scan()` requires.

## Deployment
Image built from the Fedora base; quadlet `screener.container` (long-running swing daemon).

### Intraday-scan worker role (falcon-trader #10)
On an RTH timer the screener image runs `python3 -m falcon_trader.intraday_scanner`, which:
1. **Scans** via `scan_intraday_setups()` — Polygon REST `DELAYED ~15m (Polygon REST)` during RTH
   when keyed and bars are non-empty, else flat-file `STALE`/`DEGRADED` (#9 labeling, untouched —
   this worker NEVER re-labels, upgrades, or fabricates a tier).
2. **Persists** via `persist_scan()` → one `profile_runs` row under the **"Intraday Scanner"**
   profile (run_type `intraday_scan`), reusing `ProfileManager.log_profile_run` — zero new tables.
3. The falcon-trader dashboard then **reads** that row for free through its existing ProfileManager
   merge loop, so a fresh DELAYED-labeled setup surfaces on `/api/recommendations` mid-session.

Quadlets: `intraday-scan.container` (Type=oneshot, Image=`localhost/falcon-screener:latest`,
`Network=falcon.network`, `EnvironmentFile=~/.config/falcon/falcon.env` for DATABASE_URL +
POLYGON_API_KEY + MASSIVE_*) and `intraday-scan.timer` firing every ~15 min Mon-Fri ~09:45-16:00
America/New_York — mirrors the existing `data-sync-minute` units. Execution stays DAS-only;
Polygon/Massive data stays PRIVATE to localhost:5000.

The shipped `deploy/quadlet/falcon-screener-*` units schedule the SWING screener against SQLite at
the wrong (4 AM/10 AM/7 PM/8 PM ET) cadence and are NOT the intraday worker; do not reuse them as-is.

## Status / notes
- Screener profile endpoints are currently surfaced via the dashboard Diagnostics console (issue #4).
- Data sourcing should align with the platform rule: flat files for historical, DAS for live.
