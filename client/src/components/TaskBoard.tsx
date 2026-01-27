import { useState, useEffect, useRef } from 'react';
import {
    CheckCircle2, AlertCircle, Loader2, Search,
    LayoutGrid, List, FileVideo, Terminal, Play,
    Clock, Activity, Hash, FolderOpen, ChevronRight,
    MonitorPlay, ArrowDownAZ
} from 'lucide-react';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/language';
import { motion, AnimatePresence } from 'framer-motion';

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
}

export function TaskBoard({ defaultConfig }: { defaultConfig: TaskBoardConfig }) {
    const { t } = useTranslation();
    const [tasks, setTasks] = useState<Record<string, Task>>({});
    const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
    const [sortConfig, setSortConfig] = useState<{ field: 'time' | 'name'; direction: 'desc' | 'asc' }>({ field: 'time', direction: 'desc' });
    const [showRaw, setShowRaw] = useState(false);
    const [rawLogs, setRawLogs] = useState<string[]>([]);
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
            await fetch('http://localhost:8000/api/tasks/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    input_dir: task.fullPath,
                    tmdb_id: parseInt(task.tmdbId),
                    media_type: task.mediaType,
                    dry_run: false,
                    inplace: defaultConfig.strategy !== 'copy',
                    copy_mode: defaultConfig.strategy === 'copy',
                    output_dir: defaultConfig.strategy === 'copy' ? defaultConfig.outputPath : undefined
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
        const entry = Object.entries(tasks).find(([k, v]) => v === t);
        return entry ? entry[0] : t.threadId;
    };

    useEffect(() => {
        const connect = () => {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const ws = new WebSocket(`${protocol}//localhost:8000/ws/logs`);
            wsRef.current = ws;

            ws.onmessage = (event) => {
                const msg = event.data;
                setRawLogs(prev => [...prev.slice(-200), msg]);
                parseLog(msg);
            };

            ws.onclose = () => setTimeout(connect, 3000);
        };
        connect();
        return () => wsRef.current?.close();
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
        <div className="flex flex-col h-full bg-black/20 backdrop-blur-md border border-white/5 rounded-2xl overflow-hidden shadow-2xl">
            {/* Toolbar */}
            <div className="flex items-center justify-between px-6 py-4 bg-white/5 border-b border-white/5">
                <div className="flex items-center gap-3">
                    <div className="w-2 h-2 rounded-full bg-primary animate-pulse shadow-[0_0_10px_var(--primary)]" />
                    <h3 className="font-bold text-sm uppercase tracking-widest text-white/80">
                        {t('mission_control')} <span className="opacity-50 ml-1 text-xs font-mono">({finishedCount}/{totalCount})</span>
                    </h3>
                </div>
                <div className="flex items-center gap-2">
                    {/* Sort Controls */}
                    <div className="flex bg-black/40 rounded-lg p-1 border border-white/5 mr-2">
                        <button
                            onClick={() => setSortConfig(prev => ({ field: 'time', direction: prev.field === 'time' && prev.direction === 'desc' ? 'asc' : 'desc' }))}
                            className={cn(
                                "flex items-center gap-1.5 px-3 py-1.5 rounded-md transition-all text-[10px] font-bold uppercase tracking-wider",
                                sortConfig.field === 'time' ? "bg-primary/20 text-primary shadow-inner" : "text-white/40 hover:text-white/60"
                            )}
                        >
                            <Clock className="w-3.5 h-3.5" />
                            <span>Time</span>
                            {sortConfig.field === 'time' && (
                                <ChevronRight className={cn("w-3 h-3 transition-transform", sortConfig.direction === 'asc' ? "-rotate-90" : "rotate-90")} />
                            )}
                        </button>
                        <div className="w-px bg-white/5 my-1" />
                        <button
                            onClick={() => setSortConfig(prev => ({ field: 'name', direction: prev.field === 'name' && prev.direction === 'asc' ? 'desc' : 'asc' }))}
                            className={cn(
                                "flex items-center gap-1.5 px-3 py-1.5 rounded-md transition-all text-[10px] font-bold uppercase tracking-wider",
                                sortConfig.field === 'name' ? "bg-primary/20 text-primary shadow-inner" : "text-white/40 hover:text-white/60"
                            )}
                        >
                            <ArrowDownAZ className="w-3.5 h-3.5" />
                            <span>Name</span>
                            {sortConfig.field === 'name' && (
                                <ChevronRight className={cn("w-3 h-3 transition-transform", sortConfig.direction === 'asc' ? "-rotate-90" : "rotate-90")} />
                            )}
                        </button>
                    </div>

                    <div className="flex bg-black/40 rounded-lg p-1 mr-4 border border-white/5">
                        <button onClick={() => setViewMode('grid')} className={cn("p-1.5 rounded-md transition-all", viewMode === 'grid' ? "bg-primary/20 text-primary shadow-inner" : "text-white/40 hover:text-white/60")}>
                            <LayoutGrid className="w-4 h-4" />
                        </button>
                        <button onClick={() => setViewMode('list')} className={cn("p-1.5 rounded-md transition-all", viewMode === 'list' ? "bg-primary/20 text-primary shadow-inner" : "text-white/40 hover:text-white/60")}>
                            <List className="w-4 h-4" />
                        </button>
                    </div>
                    <button onClick={() => setShowRaw(!showRaw)} className={cn("flex items-center gap-2 px-3 py-1.5 rounded-lg border text-[10px] font-bold uppercase transition-all", showRaw ? "bg-primary border-primary text-white" : "border-white/10 text-white/60 hover:border-white/20")}>
                        <Terminal className="w-3.5 h-3.5" />
                        {t('console')}
                    </button>
                </div>
            </div>

            {/* Content Area */}
            <div className="flex-1 overflow-y-auto p-6 scrollbar-thin">
                {sortedTaskList.length === 0 ? (
                    <div className="h-full flex flex-col items-center justify-center text-white/20 space-y-4">
                        <Search className="w-12 h-12 stroke-[1]" />
                        <p className="text-sm font-medium uppercase tracking-widest italic">{t('waiting_missions')}</p>
                    </div>
                ) : (
                    <div className={cn(
                        "grid gap-4 transition-all duration-500",
                        viewMode === 'grid' ? "grid-cols-1 md:grid-cols-2 xl:grid-cols-3 auto-rows-fr" : "grid-cols-1"
                    )}>
                        <AnimatePresence mode="popLayout">
                            {sortedTaskList.map(task => (
                                <TaskCard key={task.status === 'idle' ? task.threadId : (task.fullPath || task.name)} task={task} mode={viewMode} onExecute={handleExecute} />
                            ))}
                        </AnimatePresence>
                    </div>
                )}
            </div>

            {/* Raw Log Overlay */}
            <AnimatePresence>
                {showRaw && (
                    <motion.div initial={{ height: 0 }} animate={{ height: 200 }} exit={{ height: 0 }} className="bg-[#050505] border-t border-white/10 overflow-hidden">
                        <div className="p-4 font-mono text-[10px] text-white/40 overflow-y-auto h-full scrollbar-none">
                            {rawLogs.map((l, i) => <div key={i} className="mb-0.5 border-l border-white/5 pl-2">{l}</div>)}
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}

function TaskCard({ task, mode, onExecute }: { task: Task, mode: 'grid' | 'list', onExecute: (t: Task) => void }) {
    const { t } = useTranslation();
    const isCompact = mode === 'list';
    const isAuditReady = (task.status === 'dry_run' || task.status === 'audit_completed') && task.fullPath && task.tmdbId;
    const hasRun = task.hasExecuted;

    const getStatusConfig = (s: string) => {
        switch (s) {
            case 'completed': return { color: 'text-emerald-400', border: 'border-l-emerald-500', bg: 'bg-emerald-500/5', icon: CheckCircle2 };
            case 'failed': return { color: 'text-red-400', border: 'border-l-red-500', bg: 'bg-red-500/5', icon: AlertCircle };
            case 'processing': return { color: 'text-blue-400', border: 'border-l-blue-500', bg: 'bg-blue-500/5', icon: Activity };
            case 'fetching': return { color: 'text-indigo-400', border: 'border-l-indigo-500', bg: 'bg-indigo-500/5', icon: Loader2 };
            case 'searching': return { color: 'text-amber-400', border: 'border-l-amber-500', bg: 'bg-amber-500/5', icon: Search };
            case 'dry_run':
            case 'audit_completed': return { color: 'text-cyan-400', border: 'border-l-cyan-500', bg: 'bg-cyan-500/5', icon: Hash };
            default: return { color: 'text-slate-400', border: 'border-l-slate-700', bg: 'bg-white/[0.02]', icon: Clock };
        }
    };

    const statusConfig = getStatusConfig(task.status);
    const StatusIcon = statusConfig.icon;

    // Helper to translate status safely
    const getStatusLabel = (s: string) => {
        if (s === 'completed') return t('status_completed');
        if (s === 'failed') return t('status_failed');
        if (s === 'audit_completed') return t('status_audit_complete');
        // @ts-ignore
        return t(s) || s;
    };

    if (isCompact) {
        // List View: Compact Row
        return (
            <motion.div
                layout
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 10 }}
                className={cn(
                    "group flex items-center gap-4 p-3 rounded-lg border border-white/5 bg-white/[0.02] hover:bg-white/[0.04] transition-colors border-l-2",
                    statusConfig.border
                )}
            >
                {/* Icon */}
                <div className={cn("p-2 rounded-md bg-black/20", statusConfig.color)}>
                    {task.mediaType === 'tv' ? <MonitorPlay className="w-4 h-4" /> : <FileVideo className="w-4 h-4" />}
                </div>

                {/* Main Info */}
                <div className="flex-1 min-w-0 grid grid-cols-12 gap-4 items-center">
                    <div className="col-span-4 min-w-0">
                        <h4 className="font-bold text-xs text-white/90 truncate" title={task.name}>{task.name}</h4>
                        <div className="flex items-center gap-2 text-[10px] text-white/40 font-mono">
                            <span className="truncate">{task.threadId}</span>
                        </div>
                    </div>

                    {/* Status & Step */}
                    <div className="col-span-3 flex items-center gap-2 min-w-0">
                        <span className={cn("text-[10px] font-mono font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-white/5", statusConfig.color)}>
                            {getStatusLabel(task.status)}
                        </span>
                    </div>

                    {/* Log */}
                    <div className="col-span-5 text-[10px] font-mono text-white/30 truncate">
                        {task.lastLog}
                    </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2 shrink-0">
                    {isAuditReady && (
                        <button
                            onClick={(e) => { e.stopPropagation(); if (!hasRun) onExecute(task); }}
                            disabled={hasRun}
                            className={cn(
                                "p-1.5 rounded transition-colors group/btn",
                                hasRun ? "text-slate-500 cursor-not-allowed" : "hover:bg-cyan-500/20 text-cyan-400"
                            )}
                            title={hasRun ? t('task_started') : t('execute_plan')}
                        >
                            {hasRun ? <CheckCircle2 className="w-4 h-4" /> : <Play className="w-4 h-4 fill-current group-hover/btn:animate-pulse" />}
                        </button>
                    )}
                </div>
            </motion.div>
        );
    }

    // Grid View: Professional Card
    return (
        <motion.div
            layout
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            className={cn(
                "group flex flex-col rounded-xl border border-white/10 bg-zinc-900/50 hover:border-white/20 transition-all overflow-hidden shadow-sm hover:shadow-lg h-full min-h-[160px]",
                statusConfig.border && `border-l-4 ${statusConfig.border}`
            )}
        >
            {/* Header Area */}
            <div className="p-4 pb-2 flex gap-3">
                <div className={cn("p-2.5 rounded-lg bg-black/40 shrink-0 h-fit", statusConfig.color)}>
                    {task.mediaType === 'tv' ? <MonitorPlay className="w-5 h-5" /> : <FileVideo className="w-5 h-5" />}
                </div>

                <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-2">
                        <h4 className="font-bold text-sm text-white/90 line-clamp-2 leading-tight min-h-[1.25rem] group-hover:text-white transition-colors" title={task.name}>
                            {task.name}
                        </h4>
                        {/* Status Indicator (Non-overlapping) */}
                        <div className={cn("flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-white/5 border border-white/5 shrink-0", statusConfig.color)}>
                            <StatusIcon className={cn("w-3 h-3", task.status === 'processing' && "animate-spin")} />
                        </div>
                    </div>

                    <div className="flex items-center gap-2 mt-2 text-[10px] text-white/40 font-mono">
                        <span className="flex items-center gap-1 bg-white/5 px-1.5 py-0.5 rounded">
                            <Hash className="w-2.5 h-2.5" />
                            {task.tmdbId || '---'}
                        </span>
                        <span className="truncate opacity-50">{task.threadId}</span>
                    </div>
                </div>
            </div>

            {/* Body / Logs */}
            <div className="px-4 py-2 flex-1 min-h-0 flex flex-col justify-end">
                <div className="bg-black/30 rounded border border-white/5 p-2 mb-2 font-mono text-[10px] text-white/50 h-14 overflow-hidden relative">
                    <div className="absolute top-0 left-0 w-full h-full pointer-events-none bg-gradient-to-b from-transparent to-black/20" />
                    <p className="truncate opacity-70 mb-0.5 text-[9px] uppercase tracking-widest">{task.step}</p>
                    <p className="line-clamp-2 text-white/70" title={task.lastLog}>{task.lastLog}</p>
                </div>
            </div>

            {/* Footer / Actions */}
            <div className="px-4 pb-4 mt-auto">
                {isAuditReady ? (
                    <button
                        onClick={(e) => { e.stopPropagation(); if (!hasRun) onExecute(task); }}
                        disabled={hasRun}
                        className={cn(
                            "w-full py-2 rounded-lg font-bold text-[11px] uppercase tracking-widest flex items-center justify-center gap-2 transition-all shadow-lg",
                            hasRun
                                ? "bg-white/5 text-slate-500 cursor-not-allowed shadow-none border border-white/5"
                                : "bg-gradient-to-r from-cyan-500/20 to-blue-500/20 hover:from-cyan-500/30 hover:to-blue-500/30 border border-cyan-500/30 text-cyan-300 hover:scale-[1.02] active:scale-[0.98] shadow-cyan-900/10 group/btn"
                        )}
                    >
                        {hasRun ? (
                            <>
                                <CheckCircle2 className="w-3.5 h-3.5" />
                                {t('task_started') || 'Started'}
                            </>
                        ) : (
                            <>
                                <Play className="w-3.5 h-3.5 fill-current group-hover/btn:animate-pulse" />
                                {t('execute_plan')}
                            </>
                        )}
                    </button>
                ) : (
                    /* Progress or Status Bar */
                    <div className="w-full h-1 bg-white/5 rounded-full overflow-hidden">
                        <motion.div
                            className={cn("h-full", statusConfig.bg.replace('/5', '/50'))}
                            initial={{ width: 0 }}
                            animate={{
                                width: task.status === 'completed' ? '100%' :
                                    task.status === 'fetching' ? '60%' :
                                        task.status === 'processing' ? '40%' : '10%'
                            }}
                        />
                    </div>
                )}
            </div>
        </motion.div>
    );
}
