# MetaDataScraper

MetaDataScraper is a local media metadata manager for auditing, matching, scraping, and organizing movie and TV folders. It is designed for cautious library work: scan first, explain every match, generate an execution plan, then write NFO/artwork/files with rollback records.

MetaDataScraper 是一个本地媒体元数据管理器，用于审计、匹配、刮削和整理电影/电视剧目录。它的默认思路是保守的：先扫描和解释匹配，再生成执行计划，最后才写入 NFO、图片和整理文件，并保留回滚记录。

## Current Capabilities

- **Web workspaces**: Use a lightweight operations dashboard, scan libraries, configure advanced plans, review uncertain matches, inspect locked plans, watch structured execution events, repair failures, and roll back recorded changes from dedicated workflow views.
- **Read-only library scan**: Inventory movie/show folders, video/NFO/artwork counts, local TMDB IDs, filename confidence, and duplicate episode claims without contacting metadata providers or changing library files.
- **Existing asset validation**: Library Scan ignores macOS AppleDouble resource files and flags canonical artwork whose bytes do not match a recognized image format, so mislabeled SVG/HTML/error files are visible before refresh or execution.
- **Strict matching**: TMDB is the primary metadata source. Tavily is used only as a search fallback and any Tavily-found TMDB ID is re-verified against TMDB before acceptance.
- **Confirmed match memory**: Explicit choices from Match Review are saved in `logs/matches.db` and reused for equivalent future titles. Same-title releases with ambiguous years are not auto-selected.
- **Execution plans**: Audit mode produces a plan with file moves, conflicts, risks, missing episodes, metadata writes, and artwork writes.
- **Complete immutable plans**: Locked artifacts retain every planned action rather than truncating large libraries. A versioned envelope digest covers the plan and its filesystem baseline; corrupted or legacy-unverified artifacts must be audited again.
- **Confined file operations**: Preflight resolves real paths and rejects action sources or destinations outside the declared roots, including escapes through existing symbolic links.
- **Safer writes**: NFO, artwork, manifests, and file operations use atomic writes where possible. Metadata-only tasks are rollbackable too: created files are removed and overwritten files are restored from backups when their recorded fingerprints still match.
- **No silent metadata gaps**: Failed season fetches and season/episode NFO generation errors become structured plan diagnostics. Required NFO generation failures block execution; provider gaps become verification warnings and finish as partial rather than false success.
- **Execution preflight**: Plan Review checks source readability, required source files, target writability, and estimated free-space requirements. The same checks run again immediately before confirmed execution.
- **Fail-fast execution**: Required file moves, directory renames, and season/episode NFO writes stop the current item on failure instead of being logged as success. Copies publish through same-directory temporary files, and cross-volume moves record any published side effect before recovery or rollback.
- **Operation-level progress**: Directory creation, file move/copy, directory rename, and organizer NFO writes emit structured start/completion/failure events. Execution shows the current source and destination, while persisted task snapshots retain recent operation history and counts.
- **Artwork scraping**: Ranks TMDB artwork by configured language, votes, resolution, and aspect ratio; downloads `poster.jpg`, `fanart.jpg`, `banner.jpg`, `clearlogo.png`, `clearart.png`, extras/stills/actors, and records the selection policy in `artwork-manifest.json`.
- **Directory locks**: Concurrent jobs targeting the same media directory are blocked to avoid racing file operations.
- **Thread-safe manifests**: Parallel media workers serialize operation evidence, publish manifests through unique atomic temporary files, and create collision-free rollback backups.
- **Task ledger**: Jobs and structured events are persisted transactionally in `logs/task_events.db`; an existing `logs/task_events.json` ledger is imported automatically. Plan artifacts remain under `logs/plans/`.
- **Restart reconciliation**: On backend startup, persisted tasks that were still queued, running, or cancelling are marked `interrupted` because the previous worker no longer exists. They become visible in History as recovery work instead of remaining falsely active; recovery still performs manifest safety checks before rollback or retry.
- **Evidence-aware history cleanup**: Clearing history removes only non-actionable terminal records. Pending match reviews, locked plans, rollback-ready tasks, incomplete rollbacks, and interrupted tasks remain available; removed task plan artifacts are cleaned up, while media files, operation manifests, and rollback backups are left untouched.

## Quick Start

Use the project launcher from the repository root:

```bash
bash start.sh
```

`start.sh` will:

- create `.venv` with `python3` if needed;
- install Python requirements;
- install frontend dependencies if `client/node_modules` is missing;
- start the backend on `127.0.0.1:8000`;
- start the frontend on `127.0.0.1:5173`;
- wait until both health checks respond before printing `Services ready`;
- stop both services together when you press `Ctrl+C`.

Backend runtime overrides:

```bash
WEB_HOST=0.0.0.0 WEB_PORT=8000 WEB_RELOAD=1 bash start.sh
```

By default, reload is disabled so the launcher can monitor one stable backend process.
Browser requests and WebSocket connections are restricted to loopback origins
(`localhost`, `127.0.0.1`, and `::1`) by default. If the frontend is served
from another trusted device or hostname, list its complete origins explicitly:

```bash
WEB_HOST=0.0.0.0 \
WEB_ALLOWED_ORIGINS=http://192.168.1.20:5173 \
bash start.sh
```

`WEB_ALLOWED_ORIGINS` is a comma-separated list of complete `http://` or
`https://` origins. Requests without an `Origin` header, such as local CLI
scripts and health checks, remain supported. Do not use wildcard origins for
this service because it can modify local files.

Open:

```text
http://127.0.0.1:5173
```

## Configuration

The backend source of truth is:

```text
config/config.yaml
```

The frontend Settings page reads and writes this backend config through `/api/settings`. Secret values are masked when returned to the UI; leaving a masked value unchanged keeps the existing key.

Every effective settings change is recorded in `logs/settings_audit.db` as a revision containing only changed field paths and a SHA-256 configuration fingerprint. Secret values are never copied into the revision history. Saves use optimistic concurrency control, so a stale Settings page receives a conflict instead of silently overwriting a newer revision.

Each task freezes its effective runtime configuration in memory at startup and persists only the revision and fingerprint as audit evidence. Locked plans become drifted when the effective configuration changes; execution is rejected until a new plan is generated under the current policy.

Artwork policy is configured under `output.artwork_policy`. Preferred languages are ordered, followed by language-neutral images and then other languages. Minimum widths reject weak assets unless every available candidate is below the threshold, in which case the fallback is recorded in the artwork manifest.

Matching safety is configured under `matching`. Title similarity and token overlap are independent acceptance signals, while separate high-confidence thresholds control how the decision is presented. Strict year matching is enabled by default; disabling it keeps year-mismatch evidence visible even when the candidate is allowed to proceed.

NFO output uses the `output.nfo_policy` universal profile for Jellyfin, Emby, and Kodi. Movie, show, season, and episode XML are snapshot-tested. Episode sidecars and season folders are generated only for episode numbers backed by a local video file; remote episodes missing from the library remain plan risks instead of creating phantom files.

Loose-file discovery uses a structured filename parser with explicit title, year, season, episode, release-group, media-type guess, confidence, and reason fields. Files without a stable title are recorded as `quarantined`: they remain untouched, do not trigger metadata search, and are shown in the task board and history as needing a safer filename.

For local environment overrides, copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Required:

- `TMDB_API_KEY`: TMDB API read token or key.

Recommended:

- `TAVILY_API_KEY`: fallback search for difficult titles. It does not replace TMDB; IDs found through Tavily are verified by TMDB before use.

Optional:

- `OMDB_API_KEY`: reserved auxiliary metadata source.
- `HTTP_PROXY` / `HTTPS_PROXY`: proxy for TMDB/Tavily if your network needs it.
- `MODEL_*`: OpenAI-compatible endpoint for optional metadata translation.

Do not put real production secrets in `.env.example`.

## Web Workflow

1. Open **Dashboard** to see pending match/plan reviews, active executions, rollback-ready tasks, service readiness, and recent outcomes. The dashboard uses a compact aggregate endpoint and inactive workspaces are not mounted.
2. Open **Library Scan**, enter a library root such as `/Volumes/WorkStation/本地文件`, and scan it in Auto, Single, or Batch mode.
   - Auto recognizes a season/show root as one item and a library root as a batch.
   - Local NFO files may supply existing media type and TMDB IDs.
   - Duplicate episode claims, unstable filenames, missing videos, and truncated scans are surfaced for review.
   - This stage is read-only and makes no TMDB, Tavily, or model requests.
3. Resolve uncertain metadata identity in **Match Review**. Candidate evidence, confidence, rejected alternatives, and manual TMDB corrections remain separate from file-operation approval.
4. Generate an item audit from Library Scan, or open **Planning** for advanced organize/copy/scoped task configuration.
5. Choose the plan target:
   - **Metadata**: plan NFO and artwork work without moving media.
   - **Organize**: plan in-place moves and renames.
   - **Copy**: plan a copy into the configured output location.
   - Choose a destination conflict policy: block for review, skip, retain both with a numeric suffix, or overwrite files with rollback backups. Existing directories are never destructively merged.
6. Choose media/search settings:
   - **Auto / Movie / TV** controls media type inference.
   - **Smart** uses TMDB first, then Tavily fallback.
   - **TMDB** disables Tavily fallback.
   - **Tavily** forces fallback search, then still verifies through TMDB.
7. Click `PLAN`. This always performs a dry run; the public start API rejects direct execution.
8. Open **Plan Review**:
   - only the newest locked plan for each media path is shown;
   - ready, blocked, and filesystem-drifted plans are separated;
   - the immutable digest, complete operation list, conflicts, risks, and destinations are visible;
   - blocked or drifted plans cannot be executed and must be regenerated.
9. Inspect each plan:
   - match provider, confidence, rejected candidates;
   - plan conflicts/risks/metadata writes;
   - artwork counts and missing core images;
   - lock/rollback status.
   - resolved conflict strategy and the actual destination selected by the plan.
10. Click `EXECUTE`. The backend checks the plan digest and filesystem baseline before starting, then regenerates the plan before any write.
11. Follow the real task in **Execution**:
   - preflight, metadata, file organization, and verification are separate phases;
   - per-item progress and a compact structured timeline update from WebSocket events;
   - cancellation targets the selected execution and waits for the current atomic operation to stop safely.
12. Failed items can request a new plan with a manual TMDB ID and media type.
13. Confirmed review choices become reusable match mappings. They can be inspected or removed from **Settings → Confirmed Match Memory**.

The read-only scan endpoint is also available directly:

```bash
curl -X POST http://127.0.0.1:8000/api/library/scan \
  -H 'Content-Type: application/json' \
  -d '{"path":"/path/to/library","mode":"auto","use_local_nfo":true}'
```

Pending locked plans can be queried independently of the task board:

```bash
curl http://127.0.0.1:8000/api/plans/review
```

Real execution progress can be queried independently of logs:

```bash
curl http://127.0.0.1:8000/api/executions
```

The dashboard aggregate is available without fetching every task artifact:

```bash
curl http://127.0.0.1:8000/api/dashboard/summary
```

## CLI Usage

The CLI remains available for direct scripting:

```bash
.venv/bin/python main.py single "/path/to/My Movie" --dry-run
.venv/bin/python main.py single "/path/to/My Show" --tmdb-id 27205 --inplace
.venv/bin/python main.py batch "/path/to/media_library" --workers 4 --dry-run
```

Common options:

- `--dry-run`: preview without modifying files.
- `--inplace`: organize the source directory directly.
- `--copy`: copy files to the output directory.
- `--output /path/to/output`: set output directory.
- `--no-confirm`: skip prompts.
- `--use-local-nfo`: read existing NFO files for TMDB IDs.
- `--extra-images`: download extended artwork.

## Runtime Files

- `logs/web_session_*.log`: backend session logs.
- `logs/task_events.db`: SQLite task snapshots and structured event history.
- `logs/task_events.json`: legacy ledger imported automatically when the SQLite database is first created.
- `logs/matches.db`: SQLite database of explicit user-confirmed title mappings.
- `logs/plans/<task_id>/*.json`: immutable execution-plan artifacts.
- `<media>/.metadata-scraper-*.json`: operation manifests used for rollback.
- `<media>/artwork-manifest.json`: downloaded artwork metadata.

## Development Checks

```bash
npm --prefix client run build
env PYTHONPYCACHEPREFIX=/private/tmp/metadata-pycache .venv/bin/python -m unittest tests.test_settings tests.test_reliability tests.test_matching
env PYTHONPYCACHEPREFIX=/private/tmp/metadata-pycache .venv/bin/python -m compileall src/server src/batch src/core src/pipeline tests
```

## License

MIT
