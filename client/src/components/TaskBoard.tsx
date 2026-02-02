import { useState, useEffect, useRef } from 'react';
import {
    CheckCircle2, AlertCircle, RotateCcw,
    LayoutGrid, List, FileVideo, Play, Square,
    Clock, MonitorPlay, ArrowDownAZ, ArrowUp, ArrowDown,
    Activity
} from 'lucide-react';
import { motion } from 'framer-motion';
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
    posterPath?: string;
    status: 'idle' | 'searching' | 'fetching' | 'processing' | 'completed' | 'failed' | 'dry_run' | 'audit_completed' | 'stopped';
    step: string;
    lastLog: string;
    logs: string[];
    isExpanded: boolean;
    hasExecuted?: boolean;
    resultSummary?: string; // Sentence summary of result
}

export interface TaskBoardConfig {
    strategy: 'audit' | 'organize' | 'copy';
    outputPath?: string;
    forceFresh?: boolean;
    enableOrganize?: boolean;
    overwriteImages?: boolean;
    renameParentDir?: boolean;
}

export function TaskBoard({ defaultConfig }: { defaultConfig: TaskBoardConfig }) {
    const { t } = useTranslation();
    const [tasks, setTasks] = useState<Record<string, Task>>({});
    const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
    const [sortConfig, setSortConfig] = useState<{ field: 'time' | 'name' | 'status'; direction: 'desc' | 'asc' }>({ field: 'time', direction: 'desc' });
    const wsRef = useRef<WebSocket | null>(null);
    const [isScrolling, setIsScrolling] = useState(false);
    const scrollTimer = useRef<any>(null);

    const handleScroll = () => {
        setIsScrolling(true);
        if (scrollTimer.current) clearTimeout(scrollTimer.current);
        scrollTimer.current = setTimeout(() => {
            setIsScrolling(false);
        }, 2000);
    };

    // Track active TaskID per Thread and its metadata for deduplication
    const activeTaskIds = useRef<Record<string, string>>({});
    // Removed activeTaskMeta as we now use stable IDs directly

    const handleExecute = async (task: Task) => {
        console.log("handleExecute called for:", task.name, "Path:", task.fullPath, "ID:", task.tmdbId);

        if (!task.fullPath) {
            console.warn("Task missing fullPath, cannot execute.");
            return;
        }

        // Removed ID check because Audit/Loose file tasks might validly have no ID yet.
        // Removed hasExecuted check to allow Retrying/Running again.

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
                    tmdb_id: task.tmdbId ? parseInt(task.tmdbId) : 0,
                    media_type: task.mediaType,
                    dry_run: false,
                    inplace: defaultConfig.strategy !== 'copy',
                    copy_mode: defaultConfig.strategy === 'copy',
                    output_dir: defaultConfig.strategy === 'copy' ? defaultConfig.outputPath : undefined,
                    fresh: defaultConfig.forceFresh,
                    enable_organize: defaultConfig.enableOrganize,
                    overwrite_images: defaultConfig.overwriteImages,
                    rename_parent_dir: defaultConfig.renameParentDir,
                    search_mode: 'smart'
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

    const handleStop = async () => {
        try {
            await fetch(apiUrl('/api/tasks/stop'), { method: 'POST' });
        } catch (e) {
            console.error("Failed to stop tasks", e);
        }
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

            // Global Poster Extraction
            const posterMatch = message.match(/\[Poster=(.*?)\]/);
            if (posterMatch && posterMatch[1]) {
                updated.posterPath = posterMatch[1];
            }

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
            } else if (message.includes('Metadata generation failed') || message.includes('❌ No candidate found') || message.includes('任务失败')) {
                updated.status = 'failed';
                updated.step = t('error');
                updated.resultSummary = message.includes('❌') ? message.split('❌').pop()?.trim() : message;
            } else if (message.includes('Audit completed')) {
                updated.step = t('status_audit_complete');
                updated.status = 'audit_completed';
            } else if (message.includes('🏆 Task Successfully Finished') || message.includes('✅ Batch Scraper finished task')) {
                updated.status = 'completed';
                updated.step = t('finished');
                updated.resultSummary = "任务成功";
            } else if (message.includes('Skipping') && message.includes('Metadata already exists')) {
                updated.status = 'completed';
                updated.step = t('skipped_exists') || "Skipped (Exists)";
                updated.resultSummary = "任务成功，元数据已存在";
                updated.lastLog = message;
            } else if (message.includes('🛑 Stop event detected')) {
                updated.status = 'stopped';
                updated.step = 'Stopped';
            } else if (message.includes('Pipeline Error') || message.includes('Failed items')) {
                updated.status = 'failed';
                updated.step = t('error');
                // Try to extract error details
                const errMatch = message.match(/Error: (.*)/) || message.match(/Failed items: (.*)/);
                if (errMatch) {
                    updated.resultSummary = errMatch[1].substring(0, 50) + "...";
                } else {
                    updated.resultSummary = "任务执行出错";
                }
                updated.lastLog = message;
            }

            if (message.includes('🏆 Task Successfully Finished:')) {
                const posterMatch = message.match(/\[Poster=(.*?)\]/);
                if (posterMatch && posterMatch[1]) {
                    updated.posterPath = posterMatch[1];
                }
                updated.status = 'completed';
                updated.step = t('finished');
                // Detect specific success types from logs? For now based on status
                if (!updated.resultSummary) {
                    updated.resultSummary = "任务成功，媒体文件数量完整。";
                }
            } else if (message.includes('Renamed Directory:')) {
                updated.status = 'completed';
                updated.resultSummary = "任务成功，媒体文件数量完整。";
            } else if (updated.status === 'failed') {
                updated.resultSummary = "任务失败，找不到相关信息";
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
    const finishedCount = sortedTaskList.filter(t => ['completed', 'failed', 'audit_completed', 'dry_run'].includes(t.status)).length;


    return (
        <div className="flex flex-col h-full bg-transparent rounded-2xl overflow-hidden">
            {/* Header / Stats - Set to solid background to match table headers */}
            <div className="px-6 py-4 flex items-center justify-between shrink-0 z-20 bg-[var(--bg-panel)] border-b border-[var(--border-light)]">
                <div className="flex items-center gap-4">
                    <h2 className="text-sm font-bold uppercase tracking-widest text-[var(--text-main)] font-display">
                        {t('mission_control')}
                    </h2>
                    <div className="h-3 w-px bg-[var(--border-light)] hidden sm:block" />
                    <div className="flex items-center gap-4 text-[10px] font-mono mt-0.5">
                        <span className="flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
                            <span className="text-[var(--text-muted)] uppercase tracking-tight">{t('running')}</span>
                            <span className="text-[var(--text-main)] font-bold">{sortedTaskList.filter(t => ['processing', 'searching', 'fetching'].includes(t.status)).length}</span>
                        </span>
                        <span className="flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                            <span className="text-[var(--text-muted)] uppercase tracking-tight">{t('done')}</span>
                            <span className="text-[var(--text-main)] font-bold">{finishedCount}</span>
                        </span>
                    </div>
                </div>

                <div className="flex items-center gap-4">
                    {/* View Toggle */}
                    <SegmentedControl
                        options={[
                            { value: 'grid', icon: LayoutGrid, label: '' },
                            { value: 'list', icon: List, label: '' },
                        ]}
                        value={viewMode}
                        onChange={setViewMode}
                    />

                    <div className="h-8 w-px bg-border-light/50" />

                    {/* Sort Toggle */}
                    <SegmentedControl
                        options={[
                            { value: 'time', icon: Clock, label: `${t('time')} ${sortConfig.field === 'time' ? (sortConfig.direction === 'asc' ? '↑' : '↓') : ''}` },
                            { value: 'name', icon: ArrowDownAZ, label: `${t('name')} ${sortConfig.field === 'name' ? (sortConfig.direction === 'asc' ? '↑' : '↓') : ''}` },
                            { value: 'status', icon: Activity, label: `${t('status')} ${sortConfig.field === 'status' ? (sortConfig.direction === 'asc' ? '↑' : '↓') : ''}` },
                        ]}
                        value={sortConfig.field}
                        onChange={(v: any) => setSortConfig(p => ({
                            field: v,
                            direction: p.field === v ? (p.direction === 'asc' ? 'desc' : 'asc') : p.direction
                        }))}
                    />
                </div>
            </div>

            {/* Content Area */}
            <div className="flex-1 overflow-hidden pb-4">
                <div className="h-full relative overflow-hidden flex flex-col">
                    <div
                        onScroll={handleScroll}
                        className={cn(
                            "flex-1 overflow-y-auto scrollbar-thin scrollbar-hover-right scroll-smooth",
                            isScrolling && "scrollbar-active"
                        )}
                    >
                        {sortedTaskList.length === 0 ? (
                            <div className="flex flex-col items-center justify-center h-full text-slate-500 dark:text-muted-foreground gap-4 px-4">
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
                                            <th className="sticky top-0 z-50 border-b border-[var(--border-light)] px-2 py-3 w-20 text-center bg-[var(--bg-panel)]">{t('col_type')}</th>
                                            <th className="sticky top-0 z-50 border-b border-[var(--border-light)] px-4 py-3 min-w-[200px] text-center bg-[var(--bg-panel)]">{t('col_file')}</th>
                                            <th className="sticky top-0 z-50 border-b border-[var(--border-light)] px-4 py-3 min-w-[200px] text-center bg-[var(--bg-panel)] cursor-pointer hover:text-text-main transition-colors" onClick={() => setSortConfig(p => ({ field: 'name', direction: p.field === 'name' ? (p.direction === 'asc' ? 'desc' : 'asc') : 'asc' }))}>
                                                <div className="flex items-center justify-center gap-1">
                                                    {t('col_metadata_name')}
                                                    {sortConfig.field === 'name' && (sortConfig.direction === 'asc' ? <ArrowUp size={10} /> : <ArrowDown size={10} />)}
                                                </div>
                                            </th>
                                            <th className="sticky top-0 z-50 border-b border-[var(--border-light)] px-4 py-3 w-20 text-center bg-[var(--bg-panel)]">{t('col_year')}</th>
                                            <th className="sticky top-0 z-50 border-b border-[var(--border-light)] px-4 py-3 w-24 text-center bg-[var(--bg-panel)]">{t('col_tmdb_id')}</th>
                                            <th className="sticky top-0 z-50 border-b border-[var(--border-light)] px-4 py-3 w-24 text-center bg-[var(--bg-panel)] cursor-pointer hover:text-text-main transition-colors" onClick={() => setSortConfig(p => ({ field: 'status', direction: p.field === 'status' ? (p.direction === 'asc' ? 'desc' : 'asc') : 'asc' }))}>
                                                <div className="flex items-center justify-center gap-1">
                                                    {t('col_status')}
                                                    {sortConfig.field === 'status' && (sortConfig.direction === 'asc' ? <ArrowUp size={10} /> : <ArrowDown size={10} />)}
                                                </div>
                                            </th>
                                            <th className="sticky top-0 z-50 border-b border-[var(--border-light)] px-4 py-3 w-32 text-center bg-[var(--bg-panel)]">{t('col_result')}</th>
                                            <th className="sticky top-0 z-50 border-b border-[var(--border-light)] px-6 py-3 w-32 text-center bg-[var(--bg-panel)]">{t('col_actions')}</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-slate-200 dark:divide-white/10 text-xs font-sans">
                                        {sortedTaskList.map(task => (
                                            <TaskRow key={task.status === 'idle' ? task.threadId : (task.fullPath || task.name)} task={task} onExecute={handleExecute} onStop={handleStop} />
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        ) : (
                            <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-4 px-4">
                                {sortedTaskList.map(task => (
                                    <TaskCard key={task.status === 'idle' ? task.threadId : (task.fullPath || task.name)} task={task} onExecute={handleExecute} onStop={handleStop} />
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}

function TaskCard({ task, onExecute, onStop }: { task: Task, onExecute: (t: Task) => void, onStop: () => void }) {
    const isAuditReady = (task.status === 'dry_run' || task.status === 'audit_completed');
    const isRunning = task.status === 'processing' || task.status === 'searching' || task.status === 'fetching';
    const isFinished = task.status === 'completed';
    const isFailed = task.status === 'failed' || task.status === 'stopped';

    const yearMatch = task.name.match(/\((\d{4})\)/);
    const displayYear = yearMatch ? yearMatch[1] : null;
    const cleanTitle = task.name.replace(/\(\d{4}\)/, '').trim() || "Unknown";

    const getStatusInfo = (s: string) => {
        switch (s) {
            case 'completed': return { color: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400', label: 'Done' };
            case 'failed': return { color: 'bg-red-500/10 text-red-600 dark:text-red-400', label: 'Failed' };
            case 'stopped': return { color: 'bg-slate-500/10 text-slate-500', label: 'Stopped' };
            case 'processing':
            case 'fetching':
            case 'searching': return { color: 'bg-blue-500/10 text-blue-600 dark:text-blue-400 animate-pulse', label: 'Running' };
            case 'dry_run':
            case 'audit_completed': return { color: 'bg-sky-500/10 text-sky-600 dark:text-sky-400', label: 'PASS' };
            default: return { color: 'bg-slate-500/10 text-slate-500', label: 'Idle' };
        }
    };

    const statusInfo = getStatusInfo(task.status);
    const fileName = task.fullPath ? task.fullPath.split('/').pop() : task.name;

    return (
        <div className="relative group p-3 rounded-2xl border border-[var(--border-light)] bg-[var(--bg-panel)] hover:bg-[var(--bg-hover)] transition-all flex flex-col gap-3 shadow-sm hover:shadow-lg hover:border-primary/30 text-[var(--text-main)] overflow-hidden">
            <div className="flex items-start gap-3">
                {/* Poster / Icon Area */}
                <div className={cn(
                    "shrink-0 w-[50px] aspect-[2/3] rounded-lg flex items-center justify-center border border-[var(--border-light)] overflow-hidden relative shadow-sm transition-all duration-300 ease-out group-hover:scale-110 group-hover:shadow-xl group-hover:border-primary/50",
                    !task.posterPath && (task.mediaType === 'tv' ? "bg-purple-50 dark:bg-purple-900/40" : "bg-blue-50 dark:bg-blue-900/40")
                )}>
                    {task.posterPath ? (
                        <img src={task.posterPath} alt={task.name} className="w-full h-full object-cover" />
                    ) : (
                        task.mediaType === 'tv' ? <MonitorPlay size={20} className="text-purple-600 dark:text-purple-300 opacity-90" /> : <FileVideo size={20} className="text-blue-600 dark:text-blue-300 opacity-90" />
                    )}
                </div>

                <div className="min-w-0 flex-1 flex flex-col gap-1.5 pt-1">
                    <div className="flex items-start justify-between gap-2">
                        <h4 className="font-bold text-sm line-clamp-2 leading-snug text-[var(--text-main)]" title={task.name}>
                            {(isFinished || isFailed || isAuditReady) ? task.name : cleanTitle}
                        </h4>
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                        <span className={cn("shrink-0 text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border border-current/10", statusInfo.color)}>
                            {statusInfo.label}
                        </span>
                        {displayYear && <span className="text-[10px] font-mono text-[var(--text-muted)] border border-[var(--border-light)] px-1.5 rounded-md">{displayYear}</span>}
                        {task.tmdbId && <span className="text-[10px] font-mono text-[var(--text-dim)]">ID:{task.tmdbId}</span>}
                    </div>
                </div>
            </div>

            <div className="flex flex-col gap-2 pt-2 border-t border-slate-100 dark:border-white/5 mt-auto">
                <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0 flex-1">
                        <div className="text-[10px] font-mono text-[var(--text-muted)] truncate opacity-70 group-hover:opacity-100 transition-opacity" title={task.fullPath}>
                            {fileName}
                        </div>
                    </div>

                    {isAuditReady && !isRunning && !isFinished && (
                        <button
                            onClick={(e) => { e.stopPropagation(); onExecute(task); }}
                            className="relative z-10 shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all bg-yellow-400 text-black hover:bg-yellow-300 shadow-sm hover:scale-105 active:scale-95"
                        >
                            <Play size={10} fill="currentColor" className="text-white" />
                            <span className="text-white">RUN</span>
                        </button>
                    )}

                    {isRunning && (
                        <button
                            onClick={(e) => { e.stopPropagation(); onStop(); }}
                            className="relative z-10 shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all bg-red-500 text-white hover:bg-red-600 shadow-sm hover:scale-105 active:scale-95 animate-pulse"
                        >
                            <Square size={10} fill="currentColor" />
                            <span>STOP</span>
                        </button>
                    )}

                    {(isFailed || (isFinished && !task.resultSummary?.includes('成功'))) && (
                        <button
                            onClick={(e) => { e.stopPropagation(); onExecute(task); }}
                            className="relative z-10 shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all bg-blue-500 text-white hover:bg-blue-600 shadow-sm hover:scale-105 active:scale-95"
                        >
                            <RotateCcw size={10} />
                            <span>RETRY</span>
                        </button>
                    )}

                    {isFinished && task.resultSummary?.includes('成功') && (
                        <button disabled className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider bg-slate-100 dark:bg-white/5 text-slate-400 dark:text-slate-600 cursor-not-allowed">
                            <CheckCircle2 size={10} />
                            <span>Done</span>
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
}

function SegmentedControl({ options, value, onChange }: any) {
    return (
        <div className="grid auto-cols-fr grid-flow-col gap-1 p-1 bg-[var(--bg-toggle-wrapper)] rounded-lg border border-transparent dark:border-white/10 relative">
            {options.map((opt: any) => {
                const isActive = value === opt.value;
                return (
                    <button
                        key={opt.value}
                        onClick={() => onChange(opt.value)}
                        className={cn(
                            "relative z-10 flex flex-col items-center justify-center gap-1.5 py-1.5 px-3 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all",
                            isActive ? "text-[var(--text-on-active)]" : "text-text-muted hover:text-text-main"
                        )}
                        title={opt.label}
                    >
                        {isActive && (
                            <motion.div
                                layoutId={`segment-board-${options[0].value}`}
                                className="absolute inset-0 shadow-sm border border-border-light dark:border-primary/50 rounded-md bg-[var(--bg-panel)] dark:bg-[var(--primary)]"
                                initial={false}
                                transition={{ type: "spring", stiffness: 300, damping: 30 }}
                            />
                        )}
                        <span className="relative z-10 flex items-center gap-1.5">
                            {opt.icon && <opt.icon size={14} />}
                            {opt.label}
                        </span>
                    </button>
                )
            })}
        </div>
    )
}

function TaskRow({ task, onExecute, onStop }: { task: Task, onExecute: (t: Task) => void, onStop: () => void }) {
    const isAuditReady = (task.status === 'dry_run' || task.status === 'audit_completed');
    const isRunning = task.status === 'processing' || task.status === 'searching' || task.status === 'fetching';
    const isFinished = task.status === 'completed';
    const isFailed = task.status === 'failed' || task.status === 'stopped';

    const yearMatch = task.name.match(/\((\d{4})\)/);
    const displayYear = yearMatch ? yearMatch[1] : "—";
    const fileName = task.fullPath ? task.fullPath.split('/').pop() : task.name;

    return (
        <tr className="hover:bg-[var(--bg-hover)] group transition-colors border-b border-[var(--border-light)] last:border-0 text-[var(--text-main)]">
            <td className="px-6 py-4 text-center font-mono text-[10px] text-[var(--text-muted)]">
                {task.mediaType === 'tv' ? 'TV' : 'Movie'}
            </td>
            <td className="px-4 py-4 font-mono text-[10px] text-[var(--text-muted)] truncate max-w-[200px] text-center" title={task.fullPath}>
                {fileName}
            </td>
            <td className="px-4 py-4 font-mono text-[10px] text-[var(--text-muted)] truncate max-w-[200px] text-center" title={task.name}>
                {task.name}
            </td>
            <td className="px-4 py-4 font-mono text-[10px] text-[var(--text-muted)] text-center">
                {displayYear}
            </td>
            <td className="px-4 py-4 font-mono text-[10px] text-[var(--text-muted)] text-center">
                {task.tmdbId || "—"}
            </td>
            <td className="px-4 py-4 text-center">
                <span className={cn(
                    "text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full inline-block",
                    task.status === 'completed' ? "bg-emerald-100 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400" :
                        isFailed ? "bg-red-100 text-red-500 dark:bg-red-500/10" :
                            isRunning ? "bg-blue-100 text-blue-500 dark:bg-blue-500/10 animate-pulse" :
                                isAuditReady ? "bg-sky-100 text-sky-600 dark:bg-sky-500/10 dark:text-sky-400" :
                                    "bg-slate-100 text-slate-500 dark:bg-slate-800"
                )}>
                    {task.status === 'dry_run' || task.status === 'audit_completed' ? 'PASS' :
                        task.status === 'completed' ? 'Done' :
                            task.status === 'stopped' ? 'Stopped' :
                                isRunning ? 'Running' : task.status}
                </span>
            </td>
            <td className="px-4 py-4 text-xs max-w-[250px] text-center">
                {(task.resultSummary || (isFinished || isFailed || isAuditReady)) && (
                    <div className={cn("flex items-center justify-center gap-1.5 font-medium truncate",
                        (isFinished || isAuditReady) ? "text-emerald-600 dark:text-emerald-400" :
                            isFailed ? "text-red-500 dark:text-red-400" : "text-slate-500"
                    )} title={task.resultSummary || ""}>
                        {(isFinished || isAuditReady) ? <CheckCircle2 size={12} className="shrink-0" /> : isFailed ? <AlertCircle size={12} className="shrink-0" /> : null}
                        <span className="truncate">
                            {task.resultSummary || (isFinished ? "完成" : (isAuditReady ? "匹配到元数据" : (isFailed ? "失败" : "-")))}
                        </span>
                    </div>
                )}
            </td>
            <td className="px-6 py-4 text-center">
                <div className="flex justify-center gap-2">
                    {isAuditReady && !isRunning && !isFinished && (
                        <button
                            onClick={() => onExecute(task)}
                            className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all bg-yellow-400 text-black hover:bg-yellow-300 shadow-sm"
                        >
                            <Play size={10} fill="currentColor" className="text-white" />
                            <span className="text-white">RUN</span>
                        </button>
                    )}
                    {isRunning && (
                        <button
                            onClick={() => onStop()}
                            className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all bg-red-500 text-white hover:bg-red-600 shadow-sm"
                        >
                            <Square size={10} fill="currentColor" />
                            <span>STOP</span>
                        </button>
                    )}
                    {(isFailed || (isFinished && !task.resultSummary?.includes('成功'))) && (
                        <button
                            onClick={() => onExecute(task)}
                            className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all bg-blue-500 text-white hover:bg-blue-600 shadow-sm"
                        >
                            <RotateCcw size={10} />
                            <span>RETRY</span>
                        </button>
                    )}
                    {isFinished && task.resultSummary?.includes('成功') && (
                        <button disabled className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider bg-slate-100 dark:bg-white/5 text-slate-400 dark:text-slate-600 cursor-not-allowed">
                            <CheckCircle2 size={10} />
                            <span>Done</span>
                        </button>
                    )}
                </div>
            </td>
        </tr>
    );
}
