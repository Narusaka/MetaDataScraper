# Media Metadata Scraper - Web Interface Implementation Plan

**Date**: 2026-01-26
**Author**: AI Product Manager & Architect
**Version**: 1.0
**Piority**: High (Enhances User Experience & Safety)

---

## 🚀 Vision
To transform the CLI-based tool into a premium, modern Web Application that allows users to visualy monitor scraping progress, manage configurations securely, and eventually intervene in the metadata matching process.

**Design Philosophy**: "Monitor First, Control Second" — ensure visibility before adding complex interactivity.

---

## 🛠 Tech Stack
- **Backend**: Python FastAPI (Async, WebSocket support)
- **Frontend**: React (Vite) + TailwindCSS (Styling) + Framer Motion (Animations)
- **Communication**: REST API (Control) + WebSocket (Real-time Logs/Progress)
- **State**: In-Memory Job Queue (Phase 1) -> SQLite (Phase 2)

---

## 📅 Phase 1: Foundation & Monitor Mode (Estimated: 3-4 Days)
*Goal: Allow users to start a batch task from Web UI and watch the logs flow in real-time.*

### 1.1 Backend Refactoring (Python)
- [ ] **Decouple Logging**: 
    - Verify `src/core/logger.py`.
    - Create a `LogBroadcaster` class that hooks into Python's `logging` handler to push messages to a Redis queue or asyncio `Queue`.
- [ ] **Job Manager**:
    - Create `src/server/booking.py` (or `job_manager.py`) to hold the state of running tasks (Running, Idle, Error).
    - Ensure `BatchMediaScraper` can be run in a separate thread/process without blocking the API.

### 1.2 FastAPI Setup
- [ ] **Init Server**: Create `src/server/main.py`.
- [ ] **API Endpoints**:
    - `GET /api/status`: System status (workers, api usage).
    - `GET /api/filesystem`: Recursive directory walker for selecting input folders.
    - `POST /api/tasks/start`: Trigger a batch scrape (payload: `path`, `options`).
    - `POST /api/tasks/stop`: Kill current process.
- [ ] **WebSocket**:
    - `WS /ws/logs`: Endpoint that streams the `LogBroadcaster` queue to connected clients.

### 1.3 Frontend Skeleton (React)
- [ ] **Scaffold**: Initialize with `npm create vite@latest client -- --template react-ts`.
- [ ] **Styling**: Install TailwindCSS and configure `p3-color` palette (Slate/Zinc bases with Violet accents).
- [ ] **Components**:
    - `Layout`: Sidebar + Main Content Area (Glassmorphism effect).
    - `TerminalView`: A styled console window to render WebSocket logs (Matrix-style or VSCode-style).
    - `FolderPicker`: A tree-view component to select media directories.

### 1.4 Integration
- [ ] **Connect**: Frontend "Start" button hits `POST /api/tasks/start`.
- [ ] **Stream**: Frontend connects to `WS /ws/logs` and appends lines to `TerminalView`.

---

## 🎨 Phase 2: Configuration & Safety (Estimated: 2 Days)
*Goal: Replace manual `.env` editing with a secure UI.*

### 2.1 Settings Manager
- [ ] **Backend**:
    - `GET /api/config`: Read `.env` and `config.yaml` (masking actual keys like `sk-****`).
    - `POST /api/config`: Validate and write updates to `.env`.
- [ ] **Frontend**:
    - **Settings Page**: Form with validation for API Keys.
    - **Proxy Tester**: "Check Connection" button for Google/TMDB proxies.

### 2.2 Dashboard
- [ ] **Stats Widgets**:
    - Total Media Processed.
    - API Requests (estimate cost/usage).
    - Storage Saved/Used.

---

## 🧠 Phase 3: Interactive "Human-in-the-Loop" (Estimated: 4-5 Days)
*Goal: Solve the "Wrong Match" problem by allowing manual override.*

### 3.1 Review Workflow
- [ ] **Backend**:
    - Add `DryRun` endpoint that returns a JSON diff of changes instead of executing them.
    - Add `Search` endpoint (`/api/search/tmdb`) to proxy searches to TMDB.
- [ ] **Frontend**:
    - **Task Card**: Visual representation of a movie/show task.
    - **Status Indicators**:
        - 🟢 Matched (High Confidence)
        - 🟡 Low Confidence (Needs Review)
        - 🔴 Failed
    - **Intervention UI**: Click a card -> Search TMDB -> Select correct poster -> "Confirm".

### 3.2 Gallery View
- [ ] **Visual Layout**: Grid view of downloaded posters.
- [ ] **Details**: Click to see NFO content and Actor info.

---

## 📦 Phase 4: Packaging (Estimated: 1 Day)
- [ ] **Docker**: Create `Dockerfile` and `docker-compose.yml` that runs both Backend (Uvicorn) and Frontend (Nginx/Serve).
- [ ] **Startup Script**: `run_web.sh` to launch everything locally.

---

## 📝 Success Metrics
1.  **Zero Command Line**: User can set up keys and run a tasks without touching the terminal.
2.  **Visual Confirmation**: User sees exactly what's happening via real-time logs.
3.  **Safety**: No accidental overwrites (Preview Mode enforced in UI).
