# MetaDataScraper Frontend

React + TypeScript + Vite dashboard for the local MetaDataScraper backend.

## Development

From the project root, the normal path is:

```bash
bash start.sh
```

For frontend-only work:

```bash
npm install
npm run dev
```

The frontend resolves the backend from the current browser host by default:

- browser at `http://127.0.0.1:5173` -> backend `http://127.0.0.1:8000`
- browser at `http://localhost:5173` -> backend `http://localhost:8000`

Override only when needed:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_WS_BASE_URL=ws://127.0.0.1:8000
```

## UI Contract

The dashboard should treat `/api/tasks` and `/ws/events` as authoritative state. `/ws/logs` is only supporting text output.

Important backend surfaces:

- `GET /api/settings`, `POST /api/settings`
- `GET /api/status`
- `GET /api/test_connectivity`
- `POST /api/scrape`
- `POST /api/stop/{task_id}`
- `POST /api/tasks/{task_id}/rollback`
- `GET /api/tasks`
- `GET /api/tasks/{task_id}`
- `GET /api/tasks/{task_id}/plan?item_id=...`
- `WS /ws/events`
- `WS /ws/logs`

## Build

```bash
npm run build
```

Do not commit `node_modules` or generated `dist` output.
