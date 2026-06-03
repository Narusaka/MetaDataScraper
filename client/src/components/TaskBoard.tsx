import { useState, useEffect, useRef } from 'react';
import {
    CheckCircle2, AlertCircle, RotateCcw,
    LayoutGrid, List, FileVideo, Play, Square,
    Clock, MonitorPlay, ArrowDownAZ, ArrowUp, ArrowDown,
    Activity, Undo2, ChevronDown
} from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/language';
import { apiUrl, wsUrl } from '../lib/api';
import { toast } from 'sonner';

interface Task {
    taskId?: string;
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
    plan?: ExecutionPlan;
    planSummary?: PlanSummary;
    match?: MatchExplanation;
}

interface MatchExplanation {
    provider?: string | null;
    confidence?: string;
    reason?: string;
    score?: number | null;
    token_overlap?: number;
    selected_id?: number;
    selected_title?: string;
    candidates?: Array<Record<string, any>>;
}

interface PlanSummary {
    actions?: number;
    ready?: number;
    blocked?: number;
    conflicts?: number;
    risks?: number;
    media_files?: number;
    missing_episodes?: number;
}

interface ExecutionPlan {
    mode?: string;
    rollback_available?: boolean;
    target_root?: string;
    summary?: PlanSummary;
    actions?: Array<Record<string, any>>;
    risks?: Array<Record<string, any>>;
    conflicts?: Array<Record<string, any>>;
    missing_episodes?: string[];
    artwork?: Record<string, any>;
}

interface TaskEvent {
    task_id: string;
    item_id?: string;
    type: string;
    timestamp: string;
    payload: Record<string, any>;
}

interface TaskSnapshot {
    id: string;
    status: string;
    input_dir: string;
    created_at: string;
    items?: Record<string, Record<string, any>>;
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
    const eventsWsRef = useRef<WebSocket | null>(null);
    const [isScrolling, setIsScrolling] = useState(false);
    const [expandedPlans, setExpandedPlans] = useState<Record<string, boolean>>({});
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
        if ((task.planSummary?.conflicts || 0) > 0 || (task.planSummary?.blocked || 0) > 0) {
            toast.error('Plan has conflicts');
            setExpandedPlans(prev => ({ ...prev, [task.fullPath || task.threadId]: true }));
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

    const handleRollback = async (task: Task) => {
        if (!task.taskId) return;
        try {
            const response = await fetch(apiUrl(`/api/tasks/${task.taskId}/rollback`), { method: 'POST' });
            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.detail || 'Rollback failed');
            }
            const result = await response.json();
            toast.success(`Rollback ${result.status}`);
            setTasks(prev => {
                const key = Object.entries(prev).find(([_, value]) => value === task)?.[0] || task.fullPath || task.threadId;
                const existing = prev[key];
                if (!existing) return prev;
                return {
                    ...prev,
                    [key]: {
                        ...existing,
                        status: 'stopped',
                        step: 'Rolled back',
                        resultSummary: '已回滚',
                    },
                };
            });
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Rollback failed');
        }
    };

    const togglePlan = (task: Task) => {
        const key = task.fullPath || task.threadId;
        setExpandedPlans(prev => ({ ...prev, [key]: !prev[key] }));
    };

    const posterUrl = (poster?: string) => {
        if (!poster) return undefined;
        if (poster.startsWith('http')) return poster;
        return `https://image.tmdb.org/t/p/w200${poster}`;
    };

    const statusStep = (status: Task['status']) => {
        if (status === 'processing') return t('scanning');
        if (status === 'searching') return t('extended_search');
        if (status === 'fetching') return t('metadata_match');
        if (status === 'completed') return t('finished');
        if (status === 'failed') return t('error');
        if (status === 'audit_completed' || status === 'dry_run') return t('status_audit_complete');
        if (status === 'stopped') return 'Stopped';
        return t('preparing');
    };

    const normalizeStatus = (status?: string): Task['status'] => {
        if (status === 'completed') return 'completed';
        if (status === 'failed') return 'failed';
        if (status === 'audit_completed') return 'audit_completed';
        if (status === 'skipped') return 'completed';
        if (status === 'stopped') return 'stopped';
        if (status === 'fetching') return 'fetching';
        if (status === 'processing') return 'processing';
        if (status === 'planned') return 'idle';
        return 'idle';
    };

    const taskFromSnapshotItem = (snapshot: TaskSnapshot, itemId: string, item: Record<string, any>): Task => {
        const candidate = item.candidate || {};
        const plan = item.plan as ExecutionPlan | undefined;
        const match = item.match as MatchExplanation | undefined;
        const planSummary = item.plan_summary || plan?.summary;
        const status = normalizeStatus(item.status);
        const name = candidate.title || item.name || itemId.split('/').pop() || t('initializing');
        const poster = posterUrl(candidate.poster_url || candidate.poster_path || item.poster_path);
        return {
            threadId: itemId,
            taskId: snapshot.id,
            createdAt: item.created_at ? Date.parse(item.created_at) : Date.parse(snapshot.created_at),
            name,
            tmdbId: candidate.tmdb_id ? String(candidate.tmdb_id) : (item.tmdb_id ? String(item.tmdb_id) : undefined),
            mediaType: candidate.media_type || item.media_type,
            fullPath: item.path || itemId,
            posterPath: poster,
            status,
            step: statusStep(status),
            lastLog: item.error || item.result || '',
            logs: item.logs || [],
            isExpanded: false,
            hasExecuted: status === 'completed',
            resultSummary: planSummary ? `${planSummary.actions || 0} actions · ${planSummary.risks || 0} risks` : item.error || item.result,
            plan,
            planSummary,
            match,
        };
    };

    const upsertFromEvent = (event: TaskEvent) => {
        const payload = event.payload || {};

        setTasks(prev => {
            const next = { ...prev };
            if (!event.item_id) {
                if (event.type === 'task.stopped') {
                    Object.entries(next).forEach(([key, task]) => {
                        if (task.status === 'processing' || task.status === 'searching' || task.status === 'fetching') {
                            next[key] = { ...task, status: 'stopped', step: 'Stopped', lastLog: 'Task stopped' };
                        }
                    });
                }
                return next;
            }

            const key = event.item_id;
            const existing = next[key] || {
                threadId: key,
                taskId: event.task_id,
                createdAt: Date.parse(event.timestamp),
                name: payload.name || key.split('/').pop() || t('initializing'),
                status: 'idle',
                step: t('preparing'),
                lastLog: '',
                logs: [],
                isExpanded: false,
                fullPath: payload.path || key,
            } as Task;

            const updated: Task = {
                ...existing,
                taskId: event.task_id,
                name: payload.title || payload.name || existing.name,
                fullPath: payload.path || existing.fullPath || key,
                mediaType: payload.media_type || existing.mediaType,
                tmdbId: payload.tmdb_id ? String(payload.tmdb_id) : existing.tmdbId,
                posterPath: posterUrl(payload.poster_url || payload.poster_path) || existing.posterPath,
                lastLog: payload.error || payload.result || existing.lastLog,
                logs: [...existing.logs.slice(-50), `${event.type}: ${payload.error || payload.result || payload.name || payload.title || ''}`],
                plan: existing.plan,
                planSummary: existing.planSummary,
                match: existing.match,
            };

            if (event.type === 'item.started') updated.status = 'processing';
            if (event.type === 'item.planned') {
                updated.status = 'idle';
                updated.resultSummary = payload.video_count || payload.file_count
                    ? `${payload.video_count || payload.file_count} files`
                    : undefined;
            }
            if (event.type === 'item.plan_ready') {
                updated.plan = payload.plan || payload;
                updated.planSummary = updated.plan?.summary;
                updated.resultSummary = updated.planSummary
                    ? `${updated.planSummary.actions || 0} actions · ${updated.planSummary.risks || 0} risks`
                    : updated.resultSummary;
            }
            if (event.type === 'candidate.selected') updated.status = 'fetching';
            if (event.type === 'candidate.selected' && payload.match) {
                updated.match = payload.match;
            }
            if (event.type === 'item.audit_completed') {
                updated.status = 'audit_completed';
                updated.hasExecuted = false;
                updated.planSummary = payload.plan_summary || updated.planSummary;
                updated.resultSummary = updated.planSummary
                    ? `${updated.planSummary.actions || 0} actions · ${updated.planSummary.risks || 0} risks`
                    : payload.result || '检测通过/PASS';
            }
            if (event.type === 'item.completed') {
                updated.status = 'completed';
                updated.hasExecuted = true;
                updated.resultSummary = payload.result || '任务成功';
            }
            if (event.type === 'item.skipped') {
                updated.status = 'completed';
                updated.hasExecuted = true;
                updated.resultSummary = '任务成功，元数据已存在';
            }
            if (event.type === 'item.failed') {
                updated.status = 'failed';
                updated.resultSummary = payload.error || '任务失败';
            }

            updated.step = statusStep(updated.status);
            next[key] = updated;
            return next;
        });
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

    useEffect(() => {
        let closed = false;
        let reconnectTimer: number | undefined;

        const loadSnapshots = async () => {
            try {
                const response = await fetch(apiUrl('/api/tasks'));
                if (!response.ok) return;
                const data = await response.json();
                const next: Record<string, Task> = {};
                (data.tasks || []).forEach((snapshot: TaskSnapshot) => {
                    Object.entries(snapshot.items || {}).forEach(([itemId, item]) => {
                        next[itemId] = taskFromSnapshotItem(snapshot, itemId, item);
                    });
                });
                setTasks(prev => ({ ...prev, ...next }));
            } catch (error) {
                console.warn('Failed to load task snapshots', error);
            }
        };

        const connect = () => {
            if (closed) return;
            const ws = new WebSocket(wsUrl('/ws/events'));
            eventsWsRef.current = ws;

            ws.onmessage = (event) => {
                try {
                    upsertFromEvent(JSON.parse(event.data));
                } catch (error) {
                    console.warn('Invalid task event', error);
                }
            };

            ws.onclose = () => {
                if (closed) return;
                reconnectTimer = window.setTimeout(connect, 3000);
            };
        };

        loadSnapshots();
        connect();
        return () => {
            closed = true;
            if (reconnectTimer) window.clearTimeout(reconnectTimer);
            eventsWsRef.current?.close();
        };
    }, [t]);

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
            const key = task.fullPath || `${task.mediaType || 'media'}:${task.tmdbId || task.name}`;
            if (!acc[key]) {
                acc[key] = task;
            } else {
                const existing = acc[key];
                const score = (candidate: Task) => {
                    let value = 0;
                    if (candidate.fullPath) value += 4;
                    if (candidate.tmdbId) value += 3;
                    if (candidate.posterPath) value += 2;
                    if (candidate.resultSummary) value += 1;
                    if (['completed', 'failed', 'audit_completed'].includes(candidate.status)) value += 6;
                    if (['processing', 'searching', 'fetching'].includes(candidate.status)) value += 3;
                    return value;
                };

                if (score(task) > score(existing)) {
                    acc[key] = task;
                } else {
                    acc[key] = {
                        ...existing,
                        logs: [...existing.logs, ...task.logs].slice(-50),
                        posterPath: existing.posterPath || task.posterPath,
                        tmdbId: existing.tmdbId || task.tmdbId,
                        mediaType: existing.mediaType || task.mediaType,
                        resultSummary: existing.resultSummary || task.resultSummary,
                    };
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
    const runningCount = sortedTaskList.filter(t => ['processing', 'searching', 'fetching'].includes(t.status)).length;
    const failedCount = sortedTaskList.filter(t => ['failed', 'stopped'].includes(t.status)).length;
    const plannedCount = sortedTaskList.filter(t => t.status === 'idle').length;


    return (
        <div className="flex flex-col h-full bg-transparent rounded-lg overflow-hidden">
            {/* Header / Stats - Set to solid background to match table headers */}
            <div className="px-5 py-3 flex flex-wrap items-center justify-between gap-3 shrink-0 z-20 bg-[var(--bg-panel)] border-b border-[var(--border-light)]">
                <div className="flex flex-wrap items-center gap-4">
                    <h2 className="text-sm font-bold uppercase tracking-widest text-[var(--text-main)] font-display">
                        {t('mission_control')}
                    </h2>
                    <div className="h-3 w-px bg-[var(--border-light)] hidden sm:block" />
                    <div className="flex flex-wrap items-center gap-3 text-[10px] font-mono mt-0.5">
                        <span className="flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
                            <span className="text-[var(--text-muted)] uppercase tracking-tight">Queued</span>
                            <span className="text-[var(--text-main)] font-bold">{plannedCount}</span>
                        </span>
                        <span className="flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
                            <span className="text-[var(--text-muted)] uppercase tracking-tight">{t('running')}</span>
                            <span className="text-[var(--text-main)] font-bold">{runningCount}</span>
                        </span>
                        <span className="flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                            <span className="text-[var(--text-muted)] uppercase tracking-tight">{t('done')}</span>
                            <span className="text-[var(--text-main)] font-bold">{finishedCount}</span>
                        </span>
                        <span className="flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
                            <span className="text-[var(--text-muted)] uppercase tracking-tight">Failed</span>
                            <span className="text-[var(--text-main)] font-bold">{failedCount}</span>
                        </span>
                    </div>
                </div>

                <div className="flex items-center gap-3">
                    {/* View Toggle */}
                    <SegmentedControl
                        options={[
                            { value: 'grid', icon: LayoutGrid, label: '' },
                            { value: 'list', icon: List, label: '' },
                        ]}
                        value={viewMode}
                        onChange={setViewMode}
                    />

                    <div className="h-8 w-px bg-border-light/50 hidden sm:block" />

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
                                        {sortedTaskList.map(task => {
                                            const key = task.fullPath || task.threadId;
                                            return (
                                                <TaskRow
                                                    key={task.status === 'idle' ? task.threadId : (task.fullPath || task.name)}
                                                    task={task}
                                                    isPlanOpen={!!expandedPlans[key]}
                                                    onExecute={handleExecute}
                                                    onStop={handleStop}
                                                    onRollback={handleRollback}
                                                    onTogglePlan={togglePlan}
                                                />
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        ) : (
                            <div className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-3 px-4">
                                {sortedTaskList.map(task => (
                                    <TaskCard key={task.status === 'idle' ? task.threadId : (task.fullPath || task.name)} task={task} onExecute={handleExecute} onStop={handleStop} onRollback={handleRollback} isPlanOpen={!!expandedPlans[task.fullPath || task.threadId]} onTogglePlan={togglePlan} />
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}

function TaskCard({ task, onExecute, onStop, onRollback, isPlanOpen, onTogglePlan }: { task: Task, onExecute: (t: Task) => void, onStop: () => void, onRollback: (t: Task) => void, isPlanOpen: boolean, onTogglePlan: (t: Task) => void }) {
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
    const plan = task.plan;
    const planSummary = task.planSummary || plan?.summary;
    const hasPlanBlockers = (planSummary?.conflicts || 0) > 0 || (planSummary?.blocked || 0) > 0;
    const match = task.match;

    return (
        <div className="relative group p-3 rounded-lg border border-[var(--border-light)] bg-[var(--bg-panel)] hover:bg-[var(--bg-hover)] transition-colors flex flex-col gap-3 shadow-sm text-[var(--text-main)] overflow-hidden">
            <div className="flex items-start gap-3">
                {/* Poster / Icon Area */}
                <div className={cn(
                    "shrink-0 w-[50px] aspect-[2/3] rounded-md flex items-center justify-center border border-[var(--border-light)] overflow-hidden relative shadow-sm",
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
                    {match && <MatchBadge match={match} />}
                </div>
            </div>

            {(planSummary || match) && (
                <div className="rounded-md border border-[var(--border-light)] bg-[var(--bg-inner-panel)]">
                    <button
                        onClick={(e) => { e.stopPropagation(); onTogglePlan(task); }}
                        className="w-full grid grid-cols-[1fr_auto] items-center gap-2 px-2 py-2 text-left"
                        title="Details"
                    >
                        {planSummary ? (
                            <div className="grid grid-cols-4 gap-2">
                                <PlanMetric label="Actions" value={planSummary.actions || 0} />
                                <PlanMetric label="Conflicts" value={planSummary.conflicts || 0} tone={(planSummary.conflicts || 0) > 0 ? 'danger' : 'normal'} />
                                <PlanMetric label="Risks" value={planSummary.risks || 0} tone={(planSummary.risks || 0) > 0 ? 'warn' : 'normal'} />
                                <PlanMetric label="Missing" value={planSummary.missing_episodes || 0} tone={(planSummary.missing_episodes || 0) > 0 ? 'warn' : 'normal'} />
                            </div>
                        ) : (
                            <div className="min-w-0">
                                {match && <MatchBadge match={match} />}
                            </div>
                        )}
                        <ChevronDown size={14} className={cn("text-[var(--text-muted)] transition-transform", isPlanOpen && "rotate-180")} />
                    </button>
                    {isPlanOpen && (
                        <DetailsPanel match={match} plan={plan} />
                    )}
                </div>
            )}

            {plan?.target_root && (
                <div className="text-[10px] font-mono text-[var(--text-muted)] truncate rounded-md bg-black/[0.03] dark:bg-white/[0.04] px-2 py-1.5" title={plan.target_root}>
                    {plan.mode || 'plan'} → {plan.target_root.split('/').pop() || plan.target_root}
                </div>
            )}

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
                            className={cn(
                                "relative z-10 shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider transition-colors shadow-sm",
                                hasPlanBlockers ? "bg-red-500/10 text-red-500 cursor-not-allowed" : "bg-yellow-400 text-black hover:bg-yellow-300"
                            )}
                        >
                            <Play size={10} fill="currentColor" className="text-white" />
                            <span className={hasPlanBlockers ? "text-red-500" : "text-white"}>{hasPlanBlockers ? "BLOCKED" : "RUN"}</span>
                        </button>
                    )}

                    {isRunning && (
                        <button
                            onClick={(e) => { e.stopPropagation(); onStop(); }}
                            className="relative z-10 shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider transition-colors bg-red-500 text-white hover:bg-red-600 shadow-sm animate-pulse"
                        >
                            <Square size={10} fill="currentColor" />
                            <span>STOP</span>
                        </button>
                    )}

                    {(isFailed || (isFinished && !task.resultSummary?.includes('成功'))) && (
                        <button
                            onClick={(e) => { e.stopPropagation(); onExecute(task); }}
                            className="relative z-10 shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider transition-colors bg-blue-500 text-white hover:bg-blue-600 shadow-sm"
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

                    {task.taskId && (isFinished || isFailed) && (
                        <button
                            onClick={(e) => { e.stopPropagation(); onRollback(task); }}
                            className="relative z-10 shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider transition-colors bg-slate-100 dark:bg-white/10 text-[var(--text-main)] hover:bg-slate-200 dark:hover:bg-white/15 shadow-sm"
                            title="Rollback"
                        >
                            <Undo2 size={10} />
                            <span>ROLLBACK</span>
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

function PlanMetric({ label, value, tone = 'normal' }: { label: string, value: number, tone?: 'normal' | 'warn' | 'danger' }) {
    return (
        <div className="min-w-0 text-center">
            <div className={cn(
                "text-xs font-bold font-mono",
                tone === 'danger' ? "text-red-500" : tone === 'warn' ? "text-amber-500" : "text-[var(--text-main)]"
            )}>
                {value}
            </div>
            <div className="text-[8px] uppercase tracking-wider text-[var(--text-muted)] truncate">
                {label}
            </div>
        </div>
    );
}

function MatchBadge({ match }: { match: MatchExplanation }) {
    const confidence = match.confidence || 'none';
    const score = typeof match.score === 'number' ? match.score : undefined;
    const tone = confidence === 'high' || confidence === 'manual'
        ? 'ok'
        : confidence === 'medium' || confidence === 'external'
            ? 'warn'
            : confidence === 'low'
                ? 'low'
                : 'none';
    return (
        <div className={cn(
            "inline-flex max-w-full items-center gap-1.5 rounded-md border px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider",
            tone === 'ok' ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" :
                tone === 'warn' ? "border-amber-500/20 bg-amber-500/10 text-amber-600 dark:text-amber-400" :
                    tone === 'low' ? "border-red-500/20 bg-red-500/10 text-red-500" :
                        "border-[var(--border-light)] bg-slate-500/10 text-[var(--text-muted)]"
        )}>
            <span>{match.provider || 'match'}</span>
            <span>{confidence}</span>
            {score !== undefined && <span>{score.toFixed(2)}</span>}
        </div>
    );
}

function DetailsPanel({ match, plan }: { match?: MatchExplanation, plan?: ExecutionPlan }) {
    return (
        <div className="border-t border-[var(--border-light)] px-2 py-2 space-y-3">
            {match && <MatchDetails match={match} />}
            {plan && <PlanDetails plan={plan} />}
        </div>
    );
}

function MatchDetails({ match }: { match: MatchExplanation }) {
    const candidates = (match.candidates || []).slice(0, 5);
    return (
        <div className="space-y-1">
            <PlanLine
                label={match.provider || 'match'}
                value={`${match.reason || 'selected'}${typeof match.score === 'number' ? ` · ${match.score.toFixed(2)}` : ''}`}
                tone={match.confidence === 'none' || match.confidence === 'low' ? 'danger' : match.confidence === 'medium' || match.confidence === 'external' ? 'warn' : 'normal'}
            />
            {candidates.map((item, index) => (
                <PlanLine
                    key={`candidate-${index}`}
                    label={`${item.media_type || 'media'} ${item.score !== undefined ? Number(item.score).toFixed(2) : ''}`}
                    value={`${item.title || item.original_title || 'Untitled'}${item.year ? ` (${item.year})` : ''}${item.id ? ` · ${item.id}` : ''}`}
                    tone={item.id === match.selected_id ? 'normal' : 'muted'}
                />
            ))}
        </div>
    );
}

function PlanDetails({ plan }: { plan: ExecutionPlan }) {
    const actions = (plan.actions || []).slice(0, 5);
    const conflicts = (plan.conflicts || []).slice(0, 3);
    const risks = (plan.risks || []).slice(0, 3);

    return (
        <div className="space-y-2">
            {conflicts.length > 0 && (
                <div className="space-y-1">
                    {conflicts.map((item, index) => (
                        <PlanLine key={`conflict-${index}`} tone="danger" label={item.reason || 'conflict'} value={item.destination || item.source || ''} />
                    ))}
                </div>
            )}
            {risks.length > 0 && (
                <div className="space-y-1">
                    {risks.map((item, index) => (
                        <PlanLine key={`risk-${index}`} tone={item.level === 'warning' ? 'warn' : 'normal'} label={item.code || item.level || 'risk'} value={item.message || ''} />
                    ))}
                </div>
            )}
            {actions.length > 0 && (
                <div className="space-y-1">
                    {actions.map((item, index) => (
                        <PlanLine key={`action-${index}`} label={item.type || 'action'} value={compactPath(item.destination || item.source || '')} />
                    ))}
                </div>
            )}
        </div>
    );
}

function PlanLine({ label, value, tone = 'normal' }: { label: string, value: string, tone?: 'normal' | 'warn' | 'danger' | 'muted' }) {
    return (
        <div className="grid grid-cols-[74px_1fr] gap-2 text-[10px] font-mono">
            <span className={cn(
                "truncate uppercase",
                tone === 'danger' ? "text-red-500" : tone === 'warn' ? "text-amber-500" : tone === 'muted' ? "text-[var(--text-dim)]" : "text-[var(--text-muted)]"
            )}>
                {label}
            </span>
            <span className="truncate text-[var(--text-muted)]" title={value}>
                {value}
            </span>
        </div>
    );
}

function compactPath(path: string) {
    const parts = path.split('/').filter(Boolean);
    if (parts.length <= 2) return path;
    return `${parts[parts.length - 2]}/${parts[parts.length - 1]}`;
}

function TaskRow({ task, isPlanOpen, onExecute, onStop, onRollback, onTogglePlan }: { task: Task, isPlanOpen: boolean, onExecute: (t: Task) => void, onStop: () => void, onRollback: (t: Task) => void, onTogglePlan: (t: Task) => void }) {
    const isAuditReady = (task.status === 'dry_run' || task.status === 'audit_completed');
    const isRunning = task.status === 'processing' || task.status === 'searching' || task.status === 'fetching';
    const isFinished = task.status === 'completed';
    const isFailed = task.status === 'failed' || task.status === 'stopped';

    const yearMatch = task.name.match(/\((\d{4})\)/);
    const displayYear = yearMatch ? yearMatch[1] : "—";
    const fileName = task.fullPath ? task.fullPath.split('/').pop() : task.name;
    const planSummary = task.planSummary || task.plan?.summary;

    return (
        <>
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
                {task.match ? (
                    <div className="flex justify-center">
                        <MatchBadge match={task.match} />
                    </div>
                ) : planSummary ? (
                    <div className="grid grid-cols-4 gap-1 text-[9px] font-mono">
                        <span>{planSummary.actions || 0} act</span>
                        <span className={(planSummary.conflicts || 0) > 0 ? "text-red-500" : "text-[var(--text-muted)]"}>{planSummary.conflicts || 0} cf</span>
                        <span className={(planSummary.risks || 0) > 0 ? "text-amber-500" : "text-[var(--text-muted)]"}>{planSummary.risks || 0} risk</span>
                        <span className={(planSummary.missing_episodes || 0) > 0 ? "text-amber-500" : "text-[var(--text-muted)]"}>{planSummary.missing_episodes || 0} miss</span>
                    </div>
                ) : (task.resultSummary || (isFinished || isFailed || isAuditReady)) && (
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
                            className={cn(
                                "shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-colors shadow-sm",
                                ((planSummary?.conflicts || 0) > 0 || (planSummary?.blocked || 0) > 0)
                                    ? "bg-red-500/10 text-red-500 cursor-not-allowed"
                                    : "bg-yellow-400 text-black hover:bg-yellow-300"
                            )}
                        >
                            <Play size={10} fill="currentColor" className="text-white" />
                            <span className={((planSummary?.conflicts || 0) > 0 || (planSummary?.blocked || 0) > 0) ? "text-red-500" : "text-white"}>
                                {((planSummary?.conflicts || 0) > 0 || (planSummary?.blocked || 0) > 0) ? "BLOCKED" : "RUN"}
                            </span>
                        </button>
                    )}
                    {(task.plan || task.match) && (
                        <button
                            onClick={() => onTogglePlan(task)}
                            className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-colors bg-slate-100 dark:bg-white/10 text-[var(--text-main)] hover:bg-slate-200 dark:hover:bg-white/15 shadow-sm"
                            title="Details"
                        >
                            <List size={10} />
                            <span>DETAILS</span>
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
                    {task.taskId && (isFinished || isFailed) && (
                        <button
                            onClick={() => onRollback(task)}
                            className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-colors bg-slate-100 dark:bg-white/10 text-[var(--text-main)] hover:bg-slate-200 dark:hover:bg-white/15 shadow-sm"
                            title="Rollback"
                        >
                            <Undo2 size={10} />
                            <span>ROLLBACK</span>
                        </button>
                    )}
                </div>
            </td>
        </tr>
        {isPlanOpen && (task.plan || task.match) && (
            <tr className="border-b border-[var(--border-light)] bg-[var(--bg-inner-panel)]">
                <td colSpan={8} className="px-6 py-3">
                    <DetailsPanel match={task.match} plan={task.plan} />
                </td>
            </tr>
        )}
        </>
    );
}
