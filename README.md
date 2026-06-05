# MetaDataScraper

MetaDataScraper is a local media metadata manager for auditing, matching, scraping, and organizing movie and TV folders. It is designed for cautious library work: scan first, explain every match, generate an execution plan, then write NFO/artwork/files with rollback records.

MetaDataScraper 是一个本地媒体元数据管理器，用于审计、匹配、刮削和整理电影/电视剧目录。它的默认思路是保守的：先扫描和解释匹配，再生成执行计划，最后才写入 NFO、图片和整理文件，并保留回滚记录。

## Current Capabilities

- **Web dashboard**: Start jobs, watch structured task events, inspect match/plan/artwork details, retry failed items with manual TMDB IDs, and trigger rollback.
- **Strict matching**: TMDB is the primary metadata source. Tavily is used only as a search fallback and any Tavily-found TMDB ID is re-verified against TMDB before acceptance.
- **Execution plans**: Audit mode produces a plan with file moves, conflicts, risks, missing episodes, metadata writes, and artwork writes.
- **Safer writes**: NFO, artwork, manifests, and file operations use atomic writes where possible. Overwrites are backed up for rollback.
- **Artwork scraping**: Downloads `poster.jpg`, `fanart.jpg`, `banner.jpg`, `clearlogo.png`, `clearart.png`, extra posters/backdrops/logos/stills/actors, and writes `artwork-manifest.json`.
- **Directory locks**: Concurrent jobs targeting the same media directory are blocked to avoid racing file operations.
- **Task ledger**: Jobs are persisted under `logs/task_events.json`; plan artifacts are stored under `logs/plans/`.

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
- stop both services together when you press `Ctrl+C`.

Backend runtime overrides:

```bash
WEB_HOST=0.0.0.0 WEB_PORT=8000 WEB_RELOAD=1 bash start.sh
```

By default, reload is disabled so the launcher can monitor one stable backend process.

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

1. Enter a target path, for example `/Volumes/WorkStation/本地文件`.
2. Choose strategy:
   - **Audit**: scan and generate plans only.
   - **Organize**: execute in place when the plan is clear.
   - **Copy**: copy to the configured output location.
3. Choose media/search settings:
   - **Auto / Movie / TV** controls media type inference.
   - **Smart** uses TMDB first, then Tavily fallback.
   - **TMDB** disables Tavily fallback.
   - **Tavily** forces fallback search, then still verifies through TMDB.
4. Click `RUN`.
5. Inspect each task card:
   - match provider, confidence, rejected candidates;
   - plan conflicts/risks/metadata writes;
   - artwork counts and missing core images;
   - lock/rollback status.
6. Failed items can be retried with a manual TMDB ID and media type.

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
- `logs/task_events.json`: persisted task snapshots.
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
