import { useState, useEffect, useRef } from 'react';
import {
    CheckCircle2,
    LayoutGrid, List, FileVideo, Play,
    Clock, MonitorPlay, ArrowDownAZ, ChevronRight,
    Activity
} from 'lucide-react';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/language';
import { apiUrl, wsUrl } from '../lib/api';

interface Task {
    threadId: string;
    createdAt: number;
    name: string;
    tmdbId?: string;
    mediaType?: string;
    fullPath?: string;
    status: 'idle' | 'searching' | 'fetching' | 'processing' | 'completed' | 'failed' | 'dry_run' | 'audit_completed';
    step: string;
    lastLog: string;
    logs: string[];
    isExpanded: boolean;
    hasExecuted?: boolean;
}

export interface TaskBoardConfig {
    strategy: 'audit' | 'organize' | 'copy';
    outputPath?: string;
    forceFresh?: boolean;
}

export function TaskBoard({ defaultConfig }: { defaultConfig: TaskBoardConfig }) {
    const { t } = useTranslation();
    const [tasks, setTasks] = useState<Record<string, Task>>({});
    const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
    const [sortConfig, setSortConfig] = useState<{ field: 'time' | 'name' | 'status'; direction: 'desc' | 'asc' }>({ field: 'time', direction: 'desc' });
    const wsRef = useRef<WebSocket | null>(null);

    // Track active TaskID per Thread and its metadata for deduplication
    const activeTaskIds = useRef<Record<string, string>>({});
    // Removed activeTaskMeta as we now use stable IDs directly

    const handleExecute = async (task: Task) => {
        if (!task.fullPath || !task.tmdbId || task.hasExecuted) return;

        // Optimistically mark as executed to disable button immediately
        setTasks(prev => ({
            ...prev,
            [getActiveTaskId(task)]: { ...task, hasExecuted: true }
        }));

        try {
            await fetch(apiUrl('/api/tasks/start'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    input_dir: task.fullPath,
                    tmdb_id: parseInt(task.tmdbId),
                    media_type: task.mediaType,
                    dry_run: false,
                    inplace: defaultConfig.strategy !== 'copy',
                    copy_mode: defaultConfig.strategy === 'copy',
                    output_dir: defaultConfig.strategy === 'copy' ? defaultConfig.outputPath : undefined,
                    fresh: defaultConfig.forceFresh
                })
            });
        } catch (e) {
            console.error("Failed to start task", e);
            // Revert on failure if needed, or leave as is to prevent spam
        }
    };

    // Helper to find the correct key for the task
    const getActiveTaskId = (t: Task) => {
        // If the task is in the list, its key is likely its ID or threadID depending on how it was stored
        // But since we have the task object from the map value, we can search for the key or pass the key in onExecute
        // A simpler way: TaskCard logic iterates sortedTaskList.
        // We know setTasks needs the KEY. 
        // Let's modify onExecute signature or find the key.
        // Actually, we can just search:
        const entry = Object.entries(tasks).find(([_, v]) => v === t);
        return entry ? entry[0] : t.threadId;
    };

    useEffect(() => {
        let closed = false;
        let reconnectTimer: number | undefined;

        const connect = () => {
            if (closed) return;
            const ws = new WebSocket(wsUrl('/ws/logs'));
            wsRef.current = ws;

            ws.onmessage = (event) => {
                const msg = event.data;
                parseLog(msg);
            };

            ws.onclose = () => {
                if (closed) return;
                reconnectTimer = window.setTimeout(connect, 3000);
            };
        };
        connect();
        return () => {
            closed = true;
            if (reconnectTimer) window.clearTimeout(reconnectTimer);
            wsRef.current?.close();
        };
    }, []);

    const parseLog = (log: string) => {
        const match = log.match(/\[(.*?)\]\s+(\w+)\s+-\s+(.*)/);
        if (!match) return;

        const [, threadIdRaw, , message] = match;
        if (threadIdRaw === 'MainThread' || threadIdRaw.startsWith('AnyIO') || threadIdRaw.startsWith('JobManager')) return;

        // Detect "Start of Detection/Task" signals to spawn new Task IDs
        let isTaskStart = false;
        let detectedName = '';
        let detectedPath = '';

        if (message.includes('Analyzing directory:')) {
            // [Audit Mode] Analyzing directory: /path/to/Series/Season 1
            const m = message.match(/Analyzing directory:\s+(.*)/);
            if (m) {
                detectedPath = m[1];
                detectedName = detectedPath.split('/').pop() || 'Unknown';
                isTaskStart = true;
            }
        } else if (message.includes('Processing: ')) {
            // Processing: Name (ID: ...)
            const parts = message.match(/Processing:\s+(.*?)\s+\(ID:/);
            if (parts) detectedName = parts[1];
            isTaskStart = true;
        } else if (message.includes('Would process directory:')) {
            const m = message.match(/Would process directory:\s+(.*)/);
            if (m) detectedName = m[1].split('/').pop() || 'Unknown';
            isTaskStart = true;
        }

        // Logic: Map Thread -> TaskID with Deduplication
        // We use a STABLE ID based on the content (Path or Name) to prevent duplicates on re-runs.
        let stableKey = '';
        if (detectedPath) stableKey = detectedPath;
        else if (detectedName && detectedName !== 'Unknown') stableKey = detectedName;

        if (isTaskStart) {
            // If we have a stable key (Path/Name), use it as the TaskID
            if (stableKey) {
                const currentMappedId = activeTaskIds.current[threadIdRaw];
                // CRITICAL FIX: Prevent splitting "Analyzing" (Path) and "Processing" (Name) into two tasks.
                // If we already have a Path-based ID for this thread that MATCHES the Name we just found,
                // keep the Path-based ID (it's more specific).
                let skipOverride = false;
                if (currentMappedId && currentMappedId.includes('/') && detectedName) {
                    // Check if the existing path ends with the name (normal folder structure)
                    if (currentMappedId.endsWith(detectedName) || currentMappedId.includes(detectedName)) {
                        skipOverride = true;
                    }
                }

                if (!skipOverride) {
                    activeTaskIds.current[threadIdRaw] = stableKey;
                }
            }
            // If NO stable key (only thread info?), we wait or rely on threadID placeholder.
        }

        // If no active task for this thread, use threadId as placeholder (Initializing state)
        // But logs from previous runs might arrive here? 
        // We assume valid flow: Worker starts -> Emits "Analyzing" -> We create Task.
        const currentTaskId = activeTaskIds.current[threadIdRaw] || threadIdRaw;

        setTasks(prev => {
            // Cleanup Placeholder: If we just defined a Real Task (Stable Key), remove the thread placeholder
            let newState = { ...prev };

            if (activeTaskIds.current[threadIdRaw] && newState[threadIdRaw]) {
                delete newState[threadIdRaw];
            }

            const existing = newState[currentTaskId] || {
                threadId: threadIdRaw,
                createdAt: Date.now(),
                name: detectedName || t('initializing'),
                status: 'idle',
                step: t('preparing'),
                lastLog: '',
                logs: [],
                isExpanded: false,
                fullPath: detectedPath
            };
            const updated = { ...existing };
            updated.lastLog = message;
            updated.logs = [...updated.logs.slice(-50), message];

            if (message.includes('Processing: ')) {
                const parts = message.match(/Processing:\s+(.*?)\s+\(ID:\s+(.*?),\s+Query:\s+(.*?),\s+Type:\s+(.*?)\)/);
                if (parts) {
                    updated.name = parts[1];
                    updated.tmdbId = parts[2] !== 'None' ? parts[2] : undefined;
                    updated.mediaType = parts[4];
                    updated.status = 'processing';
                    updated.step = t('scanning');

                    // Force update the active mapping IF it was just a thread placeholder
                    if (!activeTaskIds.current[threadIdRaw]) {
                        // It's the first time we see a name, but we might have had a path before?
                        // If we have a stable key, use it.
                        if (stableKey) activeTaskIds.current[threadIdRaw] = stableKey;
                    }
                }
            } else if (message.includes('🕵️ AUDIT_HIT:')) {
                const pathMatch = message.match(/Path='(.*?)'/);
                const idMatch = message.match(/ID=(\d+)/);
                const titleMatch = message.match(/Title='(.*?)'/);
                const typeMatch = message.match(/Type='(.*?)'/);

                if (pathMatch) updated.fullPath = pathMatch[1];
                if (idMatch) updated.tmdbId = idMatch[1];
                if (titleMatch && titleMatch[1] !== 'None') updated.name = titleMatch[1];
                if (typeMatch) updated.mediaType = typeMatch[1];

                updated.status = 'dry_run';
                updated.step = t('audit_result');
                updated.lastLog = `Audit: Found ${updated.name} (ID: ${updated.tmdbId})`;
                // Reset hasExecuted so the user can run the plan again if they re-scan
                updated.hasExecuted = false;
            } else if (message.includes('🔍 TMDB failed')) {
                updated.status = 'searching';
                updated.step = t('extended_search');
            } else if (message.includes('✅ Selected Candidate:')) {
                const idMatch = message.match(/TMDB ID (\d+)/);
                const titleMatch = message.match(/Title='(.*?)'/);
                const typeMatch = message.match(/\(Type: (\w+)\)/);
                if (idMatch) updated.tmdbId = idMatch[1];
                if (titleMatch && titleMatch[1] !== 'None') updated.name = titleMatch[1];
                if (typeMatch) updated.mediaType = typeMatch[1];
                updated.status = 'fetching';
                updated.step = t('metadata_match');
            } else if (message.includes('📡 Processing full metadata')) {
                updated.step = t('episodes_details');
            } else if (message.includes('Renamed:')) {
                updated.step = t('organizing');
            } else if (message.includes('Would process directory:')) {
                updated.status = 'dry_run';
                updated.step = t('audit_result');
            } else if (message.includes('Metadata generation failed')) {
                updated.status = 'failed';
                updated.step = t('error');
            } else if (message.includes('Audit completed')) {
                updated.step = t('status_audit_complete');
                updated.status = 'audit_completed';
            } else if (message.includes('Skipping') && message.includes('Metadata already exists')) {
                // Handle skipped tasks as completed
                updated.status = 'completed';
                updated.step = t('skipped_exists') || "Skipped (Exists)";
                updated.lastLog = message;
            }

            if (message.includes('🏆 Task Successfully Finished:') ||
                message.includes('Renamed Directory:') ||
                (updated.status === 'processing' && message.includes('successful')) ||
                (updated.status === 'audit_completed')) { // Ensure we catch the status change we made above

                // If we marked it as audit_completed above, we don't necessarily need to overwrite status to 'completed' 
                // unless we want to finish the lifecycle.
                // But CRITICALLY: We must clear the active thread ID so the NEXT start signal creates a new card.

                if (updated.status !== 'audit_completed' && updated.status !== 'failed') {
                    updated.status = 'completed';
                    updated.step = t('finished');
                }
                // We do NOT clear activeTaskIds for stable IDs, so they stay linked.
            } else if (updated.status === 'failed') {
                // Keep failed state linked too
            }

            return { ...newState, [currentTaskId]: updated };
        });
    };

    const taskList = Object.values(tasks)
        .reduce((acc, task) => {
            // Deduplication Strategy:
            // We might have a "Real" task (long ID) and a "Placeholder" task (short thread ID) 
            // describing the SAME work (same name).
            // We want to keep the "Real" one, or the most advanced one.

            const key = `${task.threadId}-${task.name}`;
            if (!acc[key]) {
                acc[key] = task;
            } else {
                const existing = acc[key];
                // Prefer "Completed/Failed/Audit" over "Processing/Idle"
                const existingDone = ['completed', 'failed', 'audit_completed'].includes(existing.status);
                const newDone = ['completed', 'failed', 'audit_completed'].includes(task.status);

                if (newDone && !existingDone) {
                    acc[key] = task;
                } else if (newDone === existingDone) {
                    // If both are done or both active, prefer the one with a "Real" ID (longer)
                    if (task.threadId.length > existing.threadId.length) acc[key] = task;
                    // Or prefer the one with more logs?
                    else if (task.logs.length > existing.logs.length) acc[key] = task;
                }
            }
            return acc;
        }, {} as Record<string, Task>);

    const sortedTaskList = Object.values(taskList)
        .filter(t => {
            // Filter out zombie placeholders: 
            // If a task is 'idle' (Initializing) and has NO path, it is likely a stray log 
            // from before detailed processing started. We hide it to keep the count accurate.
            if (t.status === 'idle' && !t.fullPath) return false;
            return true;
        })
        .sort((a, b) => {
            const { field, direction } = sortConfig;
            let comparison = 0;

            if (field === 'time') {
                comparison = (a.createdAt || 0) - (b.createdAt || 0);
            } else if (field === 'status') {
                const priority: Record<string, number> = {
                    failed: 0,
                    processing: 1,
                    searching: 2,
                    fetching: 3,
                    dry_run: 4,
                    audit_completed: 5,
                    completed: 6,
                    idle: 7
                };
                const pA = priority[a.status] ?? 99;
                const pB = priority[b.status] ?? 99;
                comparison = pA - pB;
            } else {
                comparison = (a.name || '').localeCompare(b.name || '');
            }

            return direction === 'asc' ? comparison : -comparison;
        });

    // Stats for Display
    // We include 'dry_run' as finished because in Audit Mode, getting a result IS the finish state.
    const finishedCount = sortedTaskList.filter(t => ['completed', 'failed', 'audit_completed', 'dry_run'].includes(t.status)).length;
    const totalCount = sortedTaskList.length;

    return (
        <div className="flex flex-col h-full bg-transparent rounded-2xl overflow-hidden">
            {/* Toolbar */}
            <div className="flex items-center justify-between px-6 py-4 shrink-0">
                <div className="flex items-center gap-3">
                    <div className="w-2 h-2 rounded-full bg-primary animate-pulse shadow-[0_0_10px_var(--color-primary)]" />
                    <h3 className="tracking-widest uppercase text-xs font-bold font-display opacity-80 text-slate-800 dark:text-white">
                        {t('mission_control')} <span className="opacity-50 ml-1 text-[10px] font-mono">({finishedCount}/{totalCount})</span>
                    </h3>
                </div>
                <div className="flex items-center gap-2">
                    {/* Sort Controls */}
                    <div className="flex bg-[var(--bg-toggle-wrapper)] rounded-lg p-1 border border-transparent dark:border-white/10 mr-2 gap-1">
                        <button
                            onClick={() => setSortConfig(prev => ({ field: 'time', direction: prev.field === 'time' && prev.direction === 'desc' ? 'asc' : 'desc' }))}
                            className={cn(
                                "flex items-center gap-1.5 px-3 py-1.5 rounded-md transition-all text-[10px] font-bold uppercase tracking-wider relative",
                                sortConfig.field === 'time' ? "bg-[var(--bg-panel)] dark:bg-primary text-[var(--text-on-active)] shadow-sm" : "text-muted-foreground hover:text-foreground"
                            )}
                        >
                            <Clock className="w-3.5 h-3.5" />
                            <span>{t('time')}</span>
                            {sortConfig.field === 'time' && (
                                <ChevronRight className={cn("w-3 h-3 transition-transform opacity-50", sortConfig.direction === 'asc' ? "-rotate-90" : "rotate-90")} />
                            )}
                        </button>
                        <button
                            onClick={() => setSortConfig(prev => ({ field: 'name', direction: prev.field === 'name' && prev.direction === 'asc' ? 'desc' : 'asc' }))}
                            className={cn(
                                "flex items-center gap-1.5 px-3 py-1.5 rounded-md transition-all text-[10px] font-bold uppercase tracking-wider relative",
                                sortConfig.field === 'name' ? "bg-[var(--bg-panel)] dark:bg-primary text-[var(--text-on-active)] shadow-sm" : "text-muted-foreground hover:text-foreground"
                            )}
                        >
                            <ArrowDownAZ className="w-3.5 h-3.5" />
                            <span>{t('name')}</span>
                            {sortConfig.field === 'name' && (
                                <ChevronRight className={cn("w-3 h-3 transition-transform opacity-50", sortConfig.direction === 'asc' ? "-rotate-90" : "rotate-90")} />
                            )}
                        </button>
                        <button
                            onClick={() => setSortConfig(prev => ({ field: 'status', direction: prev.field === 'status' && prev.direction === 'asc' ? 'desc' : 'asc' }))}
                            className={cn(
                                "flex items-center gap-1.5 px-3 py-1.5 rounded-md transition-all text-[10px] font-bold uppercase tracking-wider relative",
                                sortConfig.field === 'status' ? "bg-[var(--bg-panel)] dark:bg-primary text-[var(--text-on-active)] shadow-sm" : "text-muted-foreground hover:text-foreground"
                            )}
                        >
                            <Activity className="w-3.5 h-3.5" />
                            <span>{t('status')}</span>
                            {sortConfig.field === 'status' && (
                                <ChevronRight className={cn("w-3 h-3 transition-transform opacity-50", sortConfig.direction === 'asc' ? "-rotate-90" : "rotate-90")} />
                            )}
                        </button>
                    </div>

                    <div className="flex bg-[var(--bg-toggle-wrapper)] rounded-lg p-1 mr-4 border border-transparent dark:border-white/10 gap-1">
                        <button onClick={() => setViewMode('grid')} className={cn("p-1.5 rounded-md transition-all", viewMode === 'grid' ? "bg-[var(--bg-panel)] dark:bg-primary text-[var(--text-on-active)] shadow-sm" : "text-muted-foreground hover:text-foreground")}>
                            <LayoutGrid className="w-4 h-4" />
                        </button>
                        <button onClick={() => setViewMode('list')} className={cn("p-1.5 rounded-md transition-all", viewMode === 'list' ? "bg-[var(--bg-panel)] dark:bg-primary text-[var(--text-on-active)] shadow-sm" : "text-muted-foreground hover:text-foreground")}>
                            <List className="w-4 h-4" />
                        </button>
                    </div>
                </div>
            </div>

            {/* Content Area */}
            <div className="flex-1 overflow-hidden px-4 pb-4">
                <div className="h-full relative overflow-hidden flex flex-col">
                    <div className="flex-1 overflow-y-auto scrollbar-thin scrollbar-autohide">
                        {sortedTaskList.length === 0 ? (
                            <div className="flex flex-col items-center justify-center h-full text-slate-500 dark:text-muted-foreground gap-4">
                                <div className="w-16 h-16 rounded-2xl bg-slate-200 dark:bg-white/5 flex items-center justify-center animate-pulse">
                                    <MonitorPlay className="w-8 h-8 opacity-50" />
                                </div>
                                <div className="text-center space-y-1">
                                    <p className="font-mono text-xs font-bold uppercase tracking-wider">{t('waiting_missions')}</p>
                                    <p className="text-[10px] opacity-70 max-w-sm mx-auto leading-relaxed">{t('empty_state_help')}</p>
                                </div>
                            </div>
                        ) : viewMode === 'list' ? (
                            <div className="">
                                <table className="w-full text-left border-collapse">
                                    <thead>
                                        <tr className="text-[10px] uppercase font-bold text-slate-500 dark:text-slate-400 tracking-wider">
                                            <th className="sticky top-0 z-20 bg-[#F9F9F9]/95 dark:bg-[#1C1C1E]/95 backdrop-blur-md border-b-4 border-gray-200 dark:border-white/10 px-6 py-3 w-16 text-center">{t('type')}</th>
                                            <th className="sticky top-0 z-20 bg-[#F9F9F9]/95 dark:bg-[#1C1C1E]/95 backdrop-blur-md border-b-4 border-gray-200 dark:border-white/10 px-6 py-3 min-w-[120px]">{t('name')}</th>
                                            <th className="sticky top-0 z-20 bg-[#F9F9F9]/95 dark:bg-[#1C1C1E]/95 backdrop-blur-md border-b-4 border-gray-200 dark:border-white/10 px-6 py-3 w-32">{t('status')}</th>
                                            <th className="sticky top-0 z-20 bg-[#F9F9F9]/95 dark:bg-[#1C1C1E]/95 backdrop-blur-md border-b-4 border-gray-200 dark:border-white/10 px-6 py-3 w-48">{t('current_step')}</th>
                                            <th className="sticky top-0 z-20 bg-[#F9F9F9]/95 dark:bg-[#1C1C1E]/95 backdrop-blur-md border-b-4 border-gray-200 dark:border-white/10 px-6 py-3 w-28 text-right">{t('actions')}</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y-2 divide-gray-200 dark:divide-white/10 text-xs font-sans">
                                        {sortedTaskList.map(task => (
                                            <TaskRow key={task.status === 'idle' ? task.threadId : (task.fullPath || task.name)} task={task} onExecute={handleExecute} />
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        ) : (
                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                                {sortedTaskList.map(task => (
                                    <TaskCard key={task.status === 'idle' ? task.threadId : (task.fullPath || task.name)} task={task} onExecute={handleExecute} />
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}

function TaskCard({ task, onExecute }: { task: Task, onExecute: (t: Task) => void }) {
    const { t } = useTranslation();
    const isAuditReady = (task.status === 'dry_run' || task.status === 'audit_completed') && task.fullPath && task.tmdbId;
    const hasRun = task.hasExecuted;

    // Helper to extract year if present
    const yearMatch = task.name.match(/\((\d{4})\)/);
    const displayYear = yearMatch ? yearMatch[1] : null;
    const cleanTitle = task.name.replace(/\(\d{4}\)/, '').trim() || (t('unknown_title' as any) || "Unknown Title");

    const getStatusInfo = (s: string) => {
        switch (s) {
            case 'completed': return { color: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400', label: t('status_completed') };
            case 'failed': return { color: 'bg-red-500/10 text-red-600 dark:text-red-400', label: t('status_failed') };
            case 'processing': return { color: 'bg-primary/10 text-primary animate-pulse', label: 'Processing' };
            case 'fetching': return { color: 'bg-indigo-500/10 text-indigo-600 dark:text-indigo-400', label: 'Fetching' };
            case 'searching': return { color: 'bg-amber-500/10 text-amber-600 dark:text-amber-400', label: 'Searching' };
            case 'dry_run':
            case 'audit_completed': return { color: 'bg-sky-500/10 text-sky-600 dark:text-sky-400', label: t('audit_result') };
            default: return { color: 'bg-slate-500/10 text-slate-500', label: t('idle') };
        }
    };

    const statusInfo = getStatusInfo(task.status);

    return (
        <div className="relative group p-3 rounded-xl border border-slate-200 dark:border-white/10 bg-white dark:bg-white/[0.02] hover:bg-slate-50 dark:hover:bg-white/[0.05] transition-all flex flex-col gap-3 shadow-sm hover:shadow-md hover:border-primary/20">

            {/* 1. Header Row: Icon | Title | Status */}
            <div className="flex items-start gap-3">
                {/* Icon */}
                <div className={cn(
                    "shrink-0 p-2 rounded-lg flex items-center justify-center border border-slate-100 dark:border-white/10",
                    task.mediaType === 'tv' ? "bg-purple-50 text-purple-600 dark:bg-purple-900/20 dark:text-purple-400" : "bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400"
                )}>
                    {task.mediaType === 'tv' ? <MonitorPlay size={16} /> : <FileVideo size={16} />}
                </div>

                {/* Main Content */}
                <div className="min-w-0 flex-1 flex flex-col gap-1">
                    <div className="flex items-start justify-between gap-2">
                        <h4 className="font-bold text-sm text-slate-900 dark:text-gray-100 line-clamp-1 leading-tight" title={task.name}>
                            {cleanTitle}
                        </h4>

                        {/* Status Badge */}
                        <span className={cn(
                            "shrink-0 text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full",
                            statusInfo.color
                        )}>
                            {statusInfo.label}
                        </span>
                    </div>

                    {/* Metadata Row */}
                    <div className="flex flex-wrap items-center gap-2">
                        {displayYear && (
                            <span className="text-[10px] font-mono font-medium text-slate-500 dark:text-slate-400">
                                {displayYear}
                            </span>
                        )}
                        {task.tmdbId && (
                            <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500 flex items-center gap-1">
                                <span className="w-1 h-1 rounded-full bg-slate-300 dark:bg-slate-600" />
                                TMDB {task.tmdbId}
                            </span>
                        )}
                    </div>
                </div>
            </div>

            {/* 2. Footer Row: Path (Hidden/Truncated) | Action */}
            <div className="flex items-center justify-between pt-2 border-t border-slate-100 dark:border-white/5 gap-4">
                <div className="min-w-0 flex-1 group/path relative">
                    <div className="text-[10px] font-mono text-slate-400 dark:text-slate-600 truncate transition-colors group-hover/path:text-slate-600 dark:group-hover/path:text-slate-400 cursor-help">
                        {task.fullPath ? `.../${task.fullPath.split('/').slice(-2).join('/')}` : "—"}
                    </div>
                    {/* Hover tooltip for full path */}
                    {task.fullPath && (
                        <div className="absolute bottom-full left-0 mb-2 w-max max-w-[200px] p-2 rounded bg-slate-800 text-white text-[10px] break-all opacity-0 group-hover/path:opacity-100 pointer-events-none transition-opacity z-50 shadow-xl">
                            {task.fullPath}
                        </div>
                    )}
                </div>

                {isAuditReady && (
                    <button
                        onClick={(e) => { e.stopPropagation(); if (!hasRun) onExecute(task); }}
                        disabled={hasRun}
                        className={cn(
                            "shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all",
                            hasRun
                                ? "text-slate-400 dark:text-slate-600 cursor-not-allowed"
                                : "bg-primary text-white hover:bg-primary-hover shadow-lg shadow-primary/20 hover:scale-105 active:scale-95"
                        )}
                    >
                        {hasRun ? <CheckCircle2 size={12} /> : <Play size={12} fill="currentColor" />}
                        <span>{hasRun ? t('done') : t('run')}</span>
                    </button>
                )}
            </div>

            {/* Visual Flair: Step Indicator if busy */}
            {task.status === 'processing' && (
                <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary/20 overflow-hidden rounded-b-xl">
                    <div className="h-full bg-primary/50 animate-progress origin-left" />
                </div>
            )}
        </div>
    );
}

function TaskRow({ task, onExecute }: { task: Task, onExecute: (t: Task) => void }) {
    const { t } = useTranslation();
    const isAuditReady = (task.status === 'dry_run' || task.status === 'audit_completed') && task.fullPath && task.tmdbId;
    const hasRun = task.hasExecuted;

    return (
        <tr className="hover:bg-slate-50 dark:hover:bg-white/[0.02] group transition-colors border-b border-gray-100 dark:border-white/5 last:border-0">
            {/* 1. Media Identity (Icon + Title) */}
            <td className="px-6 py-4">
                <div className="flex items-center gap-4">
                    {/* Icon Box */}
                    <div className={cn(
                        "w-10 h-10 rounded-lg flex items-center justify-center shrink-0 shadow-sm",
                        task.mediaType === 'tv'
                            ? "bg-purple-100 text-purple-600 dark:bg-purple-500/20 dark:text-purple-300"
                            : "bg-blue-100 text-blue-600 dark:bg-blue-500/20 dark:text-blue-300"
                    )}>
                        {task.mediaType === 'tv' ? <MonitorPlay size={20} /> : <FileVideo size={20} />}
                    </div>

                    {/* Title Info */}
                    <div className="flex flex-col">
                        <span className="font-bold text-sm text-slate-800 dark:text-slate-100 line-clamp-1" title={task.name}>
                            {task.name}
                        </span>
                        {(task.tmdbId || task.threadId) && (
                            <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500">
                                {task.tmdbId ? `TMDB: ${task.tmdbId}` : `ID: ${task.threadId.substring(0, 8)}`}
                            </span>
                        )}
                    </div>
                </div>
            </td>

            {/* 2. Path / Location (Members equiv) */}
            <td className="px-6 py-4 align-middle">
                <div className="flex -space-x-2 overflow-hidden items-center group/path">
                    {/* We treat "Path" as the 'Members' section - displaying it subtly */}
                    <span className="text-xs text-slate-500 dark:text-slate-400 font-medium truncate max-w-[200px]" title={task.fullPath}>
                        {task.fullPath ? `.../${task.fullPath.split('/').slice(-2).join('/')}` : "—"}
                    </span>
                </div>
            </td>

            {/* 3. Status (Budget equiv) */}
            <td className="px-6 py-4 align-middle">
                <span className={cn(
                    "text-xs font-bold",
                    task.status === 'completed' || task.status === 'audit_completed' ? "text-emerald-600 dark:text-emerald-400" :
                        task.status === 'failed' ? "text-red-500" :
                            task.status === 'processing' ? "text-blue-500 animate-pulse" :
                                "text-slate-500"
                )}>
                    {task.status === 'audit_completed' ? 'Audit Done' :
                        task.status === 'dry_run' ? 'Dry Run' :
                            t(task.status as any) || task.status}
                </span>
            </td>

            {/* 4. Current Step (Text) */}
            <td className="px-6 py-4 align-middle">
                <div className="text-xs text-slate-500 dark:text-muted truncate max-w-[200px]" title={task.lastLog}>
                    {task.step}
                </div>
            </td>

            {/* 5. Actions (Optional, kept for functionality) */}
            <td className="px-6 py-4 text-right">
                {isAuditReady && (
                    <button
                        onClick={(e) => { e.stopPropagation(); if (!hasRun) onExecute(task); }}
                        disabled={hasRun}
                        className={cn(
                            "text-[10px] uppercase font-bold tracking-wider hover:text-primary transition-colors disabled:opacity-30",
                            hasRun ? "text-slate-300" : "text-slate-500"
                        )}
                    >
                        {hasRun ? "Done" : "Run Now"}
                    </button>
                )}
            </td>
        </tr>
    );
}
