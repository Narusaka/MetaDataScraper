import { useState, useEffect, useRef } from 'react';
import {
    CheckCircle2, AlertCircle, RotateCcw,
    LayoutGrid, List, FileVideo, Play, Square,
    Clock, MonitorPlay, ArrowDownAZ, ArrowUp, ArrowDown,
    Activity, Undo2, ChevronDown, FileJson,
    type LucideIcon
} from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/languageContext';
import { toast } from 'sonner';
import { fetchPlanArtifact, fetchTaskSnapshots, openTaskEventSocket, rollbackTask, startTask, stopTasks } from '../lib/taskApi';
import type { ExecutionPlan, MatchExplanation, MetadataRecord, TaskEvent, TaskSnapshot } from '../lib/types';
import {
    asRecord,
    asString,
    asStringArray,
    applyTaskEvent,
    buildTaskStartPayload,
    deriveTaskBoardState,
    getTaskViewKey,
    taskFromSnapshot,
    taskFromSnapshotItem,
    type TaskExecutionConfig,
    type TaskFilter,
    type TaskSortConfig,
    type TaskViewLabels,
    type TaskViewModel,
} from '../lib/taskViewModel';

type Task = TaskViewModel;
export type TaskBoardConfig = TaskExecutionConfig;

export function TaskBoard({ defaultConfig }: { defaultConfig: TaskBoardConfig }) {
    const { t } = useTranslation();
    const taskLabels: TaskViewLabels = {
        scanning: t('scanning'),
        extendedSearch: t('extended_search'),
        metadataMatch: t('metadata_match'),
        finished: t('finished'),
        error: t('error'),
        auditComplete: t('status_audit_complete'),
        preparing: t('preparing'),
        initializing: t('initializing'),
    };
    const [tasks, setTasks] = useState<Record<string, Task>>({});
    const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
    const [taskFilter, setTaskFilter] = useState<TaskFilter>('focus');
    const [sortConfig, setSortConfig] = useState<TaskSortConfig>({ field: 'time', direction: 'desc' });
    const eventsWsRef = useRef<WebSocket | null>(null);
    const [isScrolling, setIsScrolling] = useState(false);
    const [expandedPlans, setExpandedPlans] = useState<Record<string, boolean>>({});
    const scrollTimer = useRef<number | null>(null);

    const resolveTaskStateKey = (state: Record<string, Task>, task: Task) => {
        const viewKey = getTaskViewKey(task);
        return Object.entries(state).find(([key, value]) => (
            key === viewKey ||
            getTaskViewKey(value) === viewKey ||
            value.threadId === task.threadId ||
            (!!task.taskId && value.taskId === task.taskId && value.fullPath === task.fullPath)
        ))?.[0] || viewKey;
    };

    const handleScroll = () => {
        setIsScrolling(true);
        if (scrollTimer.current) window.clearTimeout(scrollTimer.current);
        scrollTimer.current = window.setTimeout(() => {
            setIsScrolling(false);
        }, 2000);
    };

    const handleExecute = async (task: Task, overrides: Partial<Pick<Task, 'tmdbId' | 'mediaType'>> = {}) => {
        if (!task.fullPath) {
            toast.error('Task is missing a source path');
            return;
        }
        const nextTmdbId = overrides.tmdbId ?? task.tmdbId;
        if (nextTmdbId && Number.isNaN(parseInt(nextTmdbId))) {
            toast.error('TMDB ID must be numeric');
            return;
        }
        if ((task.planSummary?.conflicts || 0) > 0 || (task.planSummary?.blocked || 0) > 0) {
            toast.error('Plan has conflicts');
            setExpandedPlans(prev => ({ ...prev, [getTaskViewKey(task)]: true }));
            return;
        }

        // Removed ID check because Audit/Loose file tasks might validly have no ID yet.
        // Removed hasExecuted check to allow Retrying/Running again.

        // Optimistically mark as executed to disable button immediately
        setTasks(prev => {
            const activeKey = resolveTaskStateKey(prev, task);
            return {
                ...prev,
                [activeKey]: { ...(prev[activeKey] || task), hasExecuted: true }
            };
        });

        try {
            await startTask(buildTaskStartPayload(task, defaultConfig, overrides));
            toast.success('Task started');
        } catch (e) {
            setTasks(prev => {
                const activeKey = resolveTaskStateKey(prev, task);
                const existing = prev[activeKey];
                if (!existing) return prev;
                return {
                    ...prev,
                    [activeKey]: {
                        ...existing,
                        hasExecuted: false,
                        resultSummary: e instanceof Error ? e.message : 'Failed to start task',
                    },
                };
            });
            toast.error(e instanceof Error ? e.message : 'Failed to start task');
        }
    };

    const handleStop = async () => {
        try {
            await stopTasks();
        } catch (e) {
            console.error("Failed to stop tasks", e);
        }
    };

    const handleRollback = async (task: Task) => {
        if (!task.taskId) return;
        try {
            const result = await rollbackTask(task.taskId);
            toast.success(`Rollback ${result.status}`);
            setTasks(prev => {
                const key = resolveTaskStateKey(prev, task);
                const existing = prev[key];
                if (!existing) return prev;
                return {
                    ...prev,
                    [key]: {
                        ...existing,
                        status: 'stopped',
                        step: 'Rolled back',
                        rollback: result,
                        resultSummary: result.status === 'completed' ? '已回滚' : `回滚${result.status}`,
                    },
                };
            });
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Rollback failed');
        }
    };

    const togglePlan = (task: Task) => {
        const key = getTaskViewKey(task);
        setExpandedPlans(prev => ({ ...prev, [key]: !prev[key] }));
    };

    const upsertFromEvent = (event: TaskEvent) => {
        setTasks(prev => applyTaskEvent(prev, event, taskLabels));
    };

    useEffect(() => {
        let closed = false;
        let reconnectTimer: number | undefined;

        const loadSnapshots = async () => {
            try {
                const data = await fetchTaskSnapshots();
                const next: Record<string, Task> = {};
                (data.tasks || []).forEach((snapshot: TaskSnapshot) => {
                    const items = Object.entries(snapshot.items || {});
                    if (items.length === 0) {
                        next[snapshot.id] = taskFromSnapshot(snapshot, taskLabels);
                    } else {
                        items.forEach(([itemId, item]) => {
                            next[itemId] = taskFromSnapshotItem(snapshot, itemId, item, taskLabels);
                        });
                    }
                });
                setTasks(prev => ({ ...prev, ...next }));
            } catch (error) {
                console.warn('Failed to load task snapshots', error);
            }
        };

        const connect = () => {
            if (closed) return;
            const ws = openTaskEventSocket(upsertFromEvent, (error) => {
                console.warn('Invalid task event', error);
            });
            eventsWsRef.current = ws;

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
    // Keep the task event socket stable for the component lifetime; reconnecting on render-derived helpers causes duplicate streams.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const { allVisibleTasks, filteredTasks: filteredTaskList, stats } = deriveTaskBoardState(tasks, sortConfig, taskFilter);
    const { finishedCount, runningCount, failedCount, plannedCount, readyCount, issueCount, doneOnlyCount } = stats;


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

                <div className="flex flex-wrap items-center justify-end gap-2">
                    <SegmentedControl
                        options={[
                            { value: 'focus', icon: Activity, label: `Focus ${runningCount + readyCount + issueCount}` },
                            { value: 'ready', icon: Play, label: `Ready ${readyCount}` },
                            { value: 'issues', icon: AlertCircle, label: `Issues ${issueCount}` },
                            { value: 'done', icon: CheckCircle2, label: `Done ${doneOnlyCount}` },
                            { value: 'all', icon: List, label: `All ${allVisibleTasks.length}` },
                        ]}
                        value={taskFilter}
                        onChange={setTaskFilter}
                    />

                    <div className="h-8 w-px bg-border-light/50 hidden xl:block" />

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
                        onChange={(v) => setSortConfig(p => ({
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
                        {filteredTaskList.length === 0 ? (
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
                                        {filteredTaskList.map(task => {
                                            const key = getTaskViewKey(task);
                                            return (
                                                <TaskRow
                                                    key={key}
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
                                {filteredTaskList.map(task => (
                                    <TaskCard key={getTaskViewKey(task)} task={task} onExecute={handleExecute} onStop={handleStop} onRollback={handleRollback} isPlanOpen={!!expandedPlans[getTaskViewKey(task)]} onTogglePlan={togglePlan} />
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}

function TaskCard({ task, onExecute, onStop, onRollback, isPlanOpen, onTogglePlan }: { task: Task, onExecute: (t: Task, overrides?: Partial<Pick<Task, 'tmdbId' | 'mediaType'>>) => void, onStop: () => void, onRollback: (t: Task) => void, isPlanOpen: boolean, onTogglePlan: (t: Task) => void }) {
    const isAuditReady = (task.status === 'dry_run' || task.status === 'audit_completed');
    const isRunning = task.status === 'processing' || task.status === 'searching' || task.status === 'fetching';
    const isFinished = task.status === 'completed';
    const isFailed = task.status === 'failed' || task.status === 'partial' || task.status === 'stopped';

    const yearMatch = task.name.match(/\((\d{4})\)/);
    const displayYear = yearMatch ? yearMatch[1] : null;
    const cleanTitle = task.name.replace(/\(\d{4}\)/, '').trim() || "Unknown";

    const getStatusInfo = (s: string) => {
        switch (s) {
            case 'completed': return { color: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400', label: 'Done' };
            case 'partial': return { color: 'bg-amber-500/10 text-amber-600 dark:text-amber-400', label: 'Partial' };
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
    const canRollback = !!task.taskId && !!task.rollbackAvailable && (isFinished || isFailed) && task.rollback?.status !== 'completed';

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

            {(planSummary || match || task.artwork || task.issue || task.lock || task.rollback) && (
                <div className="rounded-md border border-[var(--border-light)] bg-[var(--bg-inner-panel)]">
                    <button
                        onClick={(e) => { e.stopPropagation(); onTogglePlan(task); }}
                        className="w-full grid grid-cols-[1fr_auto] items-center gap-2 px-2 py-2 text-left"
                        title="Details"
                    >
                        {planSummary ? (
                            <div className="grid grid-cols-[repeat(auto-fit,minmax(58px,1fr))] gap-2">
                                <PlanMetric label="Actions" value={planSummary.actions || 0} />
                                <PlanMetric label="Conflicts" value={planSummary.conflicts || 0} tone={(planSummary.conflicts || 0) > 0 ? 'danger' : 'normal'} />
                                <PlanMetric label="Risks" value={planSummary.risks || 0} tone={(planSummary.risks || 0) > 0 ? 'warn' : 'normal'} />
                                <PlanMetric label="Missing" value={planSummary.missing_episodes || 0} tone={(planSummary.missing_episodes || 0) > 0 ? 'warn' : 'normal'} />
                                <PlanMetric label="Meta" value={planSummary.metadata_writes || 0} />
                            </div>
                        ) : (
                            <div className="min-w-0">
                                {match && <MatchBadge match={match} />}
                            </div>
                        )}
                        <ChevronDown size={14} className={cn("text-[var(--text-muted)] transition-transform", isPlanOpen && "rotate-180")} />
                    </button>
                    {isPlanOpen && (
                        <DetailsPanel taskId={task.taskId} itemId={task.threadId} config={task.config} issue={task.issue} match={match} plan={plan} planPath={task.planPath} artwork={task.artwork} rollback={task.rollback} lock={task.lock} />
                    )}
                </div>
            )}

            {plan?.target_root && (
                <div className="text-[10px] font-mono text-[var(--text-muted)] truncate rounded-md bg-black/[0.03] dark:bg-white/[0.04] px-2 py-1.5" title={plan.target_root}>
                    {plan.mode || 'plan'} → {plan.target_root.split('/').pop() || plan.target_root}
                </div>
            )}

            {isFailed && (
                <ManualRetryPanel task={task} onExecute={onExecute} />
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
                            disabled={hasPlanBlockers}
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

                    {isFailed && (
                        <button
                            onClick={(e) => { e.stopPropagation(); onExecute(task); }}
                            className="relative z-10 shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider transition-colors bg-blue-500 text-white hover:bg-blue-600 shadow-sm"
                        >
                            <RotateCcw size={10} />
                            <span>RETRY</span>
                        </button>
                    )}

                    {isFinished && (
                        <button disabled className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider bg-slate-100 dark:bg-white/5 text-slate-400 dark:text-slate-600 cursor-not-allowed">
                            <CheckCircle2 size={10} />
                            <span>Done</span>
                        </button>
                    )}

                    {canRollback && (
                        <button
                            onClick={(e) => { e.stopPropagation(); onRollback(task); }}
                            className="relative z-10 shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider transition-colors bg-slate-100 dark:bg-white/10 text-[var(--text-main)] hover:bg-slate-200 dark:hover:bg-white/15 shadow-sm"
                            title="Rollback"
                        >
                            <Undo2 size={10} />
                            <span>ROLLBACK</span>
                        </button>
                    )}
                    {task.rollback?.status === 'completed' && (
                        <span className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
                            <Undo2 size={10} />
                            <span>ROLLED BACK</span>
                        </span>
                    )}
                </div>
            </div>
        </div>
    );
}

function ManualRetryPanel({ task, onExecute, compact = false }: { task: Task, onExecute: (t: Task, overrides?: Partial<Pick<Task, 'tmdbId' | 'mediaType'>>) => void, compact?: boolean }) {
    const [manualTmdbId, setManualTmdbId] = useState(task.tmdbId || '');
    const [manualMediaType, setManualMediaType] = useState<'movie' | 'tv'>((task.mediaType === 'movie' || task.mediaType === 'tv') ? task.mediaType : 'movie');
    const canRun = !manualTmdbId || /^\d+$/.test(manualTmdbId.trim());

    return (
        <div className={cn(
            "rounded-md border border-red-500/15 bg-red-500/[0.04] p-2",
            compact ? "flex flex-wrap items-center justify-end gap-2" : "space-y-2"
        )}>
            <div className={cn("flex items-center gap-1", compact ? "order-2" : "")}>
                <button
                    onClick={() => setManualMediaType('movie')}
                    className={cn(
                        "h-7 px-2 rounded-md text-[10px] font-bold uppercase tracking-wider border transition-colors",
                        manualMediaType === 'movie' ? "border-blue-500/40 bg-blue-500/10 text-blue-500" : "border-[var(--border-light)] text-[var(--text-muted)]"
                    )}
                >
                    Movie
                </button>
                <button
                    onClick={() => setManualMediaType('tv')}
                    className={cn(
                        "h-7 px-2 rounded-md text-[10px] font-bold uppercase tracking-wider border transition-colors",
                        manualMediaType === 'tv' ? "border-purple-500/40 bg-purple-500/10 text-purple-500" : "border-[var(--border-light)] text-[var(--text-muted)]"
                    )}
                >
                    TV
                </button>
            </div>
            <div className={cn("flex items-center gap-2", compact ? "order-1" : "")}>
                <input
                    value={manualTmdbId}
                    onChange={(event) => setManualTmdbId(event.target.value)}
                    placeholder="TMDB ID"
                    className={cn(
                        "h-7 min-w-0 rounded-md border bg-[var(--bg-panel)] px-2 text-[10px] font-mono outline-none transition-colors",
                        canRun ? "border-[var(--border-light)] text-[var(--text-main)] focus:border-blue-500/50" : "border-red-500/50 text-red-500"
                    )}
                />
                <button
                    disabled={!canRun}
                    onClick={() => onExecute(task, { tmdbId: manualTmdbId.trim() || undefined, mediaType: manualMediaType })}
                    className={cn(
                        "h-7 shrink-0 rounded-md px-2 text-[10px] font-bold uppercase tracking-wider transition-colors",
                        canRun ? "bg-blue-500 text-white hover:bg-blue-600" : "bg-red-500/10 text-red-500 cursor-not-allowed"
                    )}
                    title="Retry with manual match"
                >
                    Fix Retry
                </button>
            </div>
        </div>
    );
}

interface SegmentOption<T extends string> {
    value: T;
    icon?: LucideIcon;
    label: string;
}

interface SegmentedControlProps<T extends string> {
    options: Array<SegmentOption<T>>;
    value: T;
    onChange: (value: T) => void;
}

function SegmentedControl<T extends string>({ options, value, onChange }: SegmentedControlProps<T>) {
    return (
        <div className="grid shrink-0 auto-cols-fr grid-flow-col gap-1 p-1 bg-[var(--bg-toggle-wrapper)] rounded-lg border border-transparent dark:border-white/10 relative">
            {options.map((opt) => {
                const isActive = value === opt.value;
                return (
                    <button
                        key={opt.value}
                        onClick={() => onChange(opt.value)}
                        className={cn(
                            "relative z-10 flex h-8 min-w-[42px] items-center justify-center gap-1.5 whitespace-nowrap py-1.5 px-3 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all",
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
                        <span className="relative z-10 flex items-center gap-1.5 whitespace-nowrap">
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

function DetailsPanel({ taskId, itemId, config, issue, match, plan, planPath, artwork, rollback, lock }: { taskId?: string, itemId?: string, config?: MetadataRecord, issue?: MetadataRecord, match?: MatchExplanation, plan?: ExecutionPlan, planPath?: string, artwork?: MetadataRecord, rollback?: MetadataRecord, lock?: MetadataRecord }) {
    return (
        <div className="border-t border-[var(--border-light)] px-2 py-2 space-y-3">
            {issue && <IssueDetails issue={issue} />}
            {config && <TaskConfigDetails config={config} />}
            {match && <MatchDetails match={match} />}
            {plan && <PlanDetails plan={plan} planPath={planPath} taskId={taskId} itemId={itemId} />}
            {lock && <LockDetails lock={lock} />}
            {artwork && <ArtworkDetails artwork={artwork} />}
            {rollback && <RollbackDetails rollback={rollback} />}
        </div>
    );
}

function IssueDetails({ issue }: { issue: MetadataRecord }) {
    const status = asString(issue.status) || 'issue';
    const error = asString(issue.error);
    const result = asString(issue.result);
    const path = asString(issue.path);
    const name = asString(issue.name);
    return (
        <div className="space-y-1">
            <PlanLine label={status} value={error || result || name || 'Needs attention'} tone={error ? 'danger' : 'warn'} />
            {path && <PlanLine label="path" value={compactPath(path)} tone="muted" />}
        </div>
    );
}

function TaskConfigDetails({ config }: { config: MetadataRecord }) {
    const strategy = asString(config.strategy) || (config.dry_run ? 'audit' : 'organize');
    const mediaType = asString(config.media_type) || 'auto';
    const multiMode = config.multi_mode === undefined || config.multi_mode === null ? 'auto' : (config.multi_mode ? 'batch' : 'single');
    return (
        <div className="space-y-1">
            <PlanLine label="config" value={`${strategy} · ${asString(config.search_mode) || 'smart'} · ${mediaType} · ${multiMode}`} tone="muted" />
            <PlanLine label="options" value={`${Number(config.workers || 1)} workers · extra ${config.extra_images ? 'on' : 'off'} · organize ${config.enable_organize ? 'on' : 'off'}`} tone="muted" />
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
                    label={`${asString(item.decision) || (item.id === match.selected_id ? 'selected' : 'candidate')} · ${asString(item.media_type) || 'media'} ${item.score !== undefined ? Number(item.score).toFixed(2) : ''}`}
                    value={`${asString(item.title) || asString(item.original_title) || 'Untitled'}${item.year ? ` (${item.year})` : ''}${item.id ? ` · ${item.id}` : ''}${item.token_overlap !== undefined ? ` · overlap ${Number(item.token_overlap).toFixed(2)}` : ''}`}
                    tone={item.decision === 'selected' || item.id === match.selected_id ? 'normal' : item.decision === 'year_mismatch' || item.decision === 'low_similarity' ? 'danger' : 'muted'}
                />
            ))}
        </div>
    );
}

function PlanDetails({ plan, planPath, taskId, itemId }: { plan: ExecutionPlan, planPath?: string, taskId?: string, itemId?: string }) {
    const actions = (plan.actions || []).slice(0, 5);
    const conflicts = (plan.conflicts || []).slice(0, 3);
    const risks = (plan.risks || []).slice(0, 3);

    return (
        <div className="space-y-2">
            {planPath && (
                <PlanArtifactLine planPath={planPath} taskId={taskId} itemId={itemId} />
            )}
            {conflicts.length > 0 && (
                <div className="space-y-1">
                    {conflicts.map((item, index) => (
                        <PlanLine key={`conflict-${index}`} tone="danger" label={asString(item.reason) || 'conflict'} value={asString(item.destination) || asString(item.source) || ''} />
                    ))}
                </div>
            )}
            {risks.length > 0 && (
                <div className="space-y-1">
                    {risks.map((item, index) => (
                        <PlanLine key={`risk-${index}`} tone={item.level === 'warning' ? 'warn' : 'normal'} label={asString(item.code) || asString(item.level) || 'risk'} value={asString(item.message) || ''} />
                    ))}
                </div>
            )}
            {actions.length > 0 && (
                <div className="space-y-1">
                    {actions.map((item, index) => (
                        <PlanLine key={`action-${index}`} label={`${asString(item.type) || 'action'}${item.kind ? ` · ${item.kind}` : ''}`} value={compactPath(asString(item.destination) || asString(item.source) || '')} />
                    ))}
                </div>
            )}
        </div>
    );
}

function PlanArtifactLine({ planPath, taskId, itemId }: { planPath: string, taskId?: string, itemId?: string }) {
    const [summary, setSummary] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const canLoad = !!taskId && !!itemId;

    const loadArtifact = async () => {
        if (!canLoad || loading) return;
        setLoading(true);
        try {
            const artifact = await fetchPlanArtifact(taskId, itemId);
            const actionCount = artifact?.plan?.summary?.actions ?? artifact?.plan?.actions?.length ?? 0;
            const generated = artifact?.generated_at ? new Date(artifact.generated_at).toLocaleString() : 'loaded';
            setSummary(`${actionCount} actions · ${generated}`);
            toast.success('Plan artifact loaded');
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Plan artifact unavailable');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="grid grid-cols-[74px_1fr_auto] gap-2 text-[10px] font-mono items-center">
            <span className="truncate uppercase text-[var(--text-dim)]">artifact</span>
            <span className="truncate text-[var(--text-muted)]" title={summary || planPath}>
                {summary || planPath}
            </span>
            <button
                type="button"
                disabled={!canLoad || loading}
                onClick={loadArtifact}
                className={cn(
                    "inline-flex h-6 w-6 items-center justify-center rounded-md border border-[var(--border-light)] text-[var(--text-muted)] hover:text-[var(--text-main)] hover:bg-[var(--bg-hover)] disabled:opacity-40 disabled:cursor-not-allowed"
                )}
                title="Load plan artifact"
            >
                <FileJson size={12} />
            </button>
        </div>
    );
}

function LockDetails({ lock }: { lock: MetadataRecord }) {
    const owner = lock.owner;
    const ownerRecord = asRecord(owner);
    const ownerLabel = typeof owner === 'string' ? owner : (ownerRecord.owner || ownerRecord.task_id || ownerRecord.pid || 'unknown');
    return (
        <div className="space-y-1">
            <PlanLine label="lock" value={compactPath(String(lock.target_path || 'target locked'))} tone="danger" />
            <PlanLine label="owner" value={String(ownerLabel)} tone="warn" />
        </div>
    );
}

function RollbackDetails({ rollback }: { rollback: MetadataRecord }) {
    const operations = Array.isArray(rollback.operations) ? rollback.operations.slice(0, 5) : [];
    const rollbackStatus = asString(rollback.status) || 'unknown';
    return (
        <div className="space-y-1">
            <PlanLine
                label="rollback"
                value={`${rollbackStatus}${operations.length ? ` · ${operations.length} ops` : ''}`}
                tone={rollbackStatus === 'completed' ? 'normal' : rollbackStatus === 'failed' ? 'danger' : 'warn'}
            />
            {operations.map((item, index: number) => {
                const operation = asRecord(item);
                const operationStatus = asString(operation.status);
                const warningStatuses = new Set(['missing_destination', 'dir_not_empty', 'missing_backup', 'current_modified']);
                return (
                <PlanLine
                    key={`rollback-${index}`}
                    label={operationStatus || asString(operation.action) || 'op'}
                    value={compactPath(asString(operation.source) || asString(operation.destination) || '')}
                    tone={operationStatus === 'failed' ? 'danger' : warningStatuses.has(operationStatus || '') ? 'warn' : 'muted'}
                />
                );
            })}
        </div>
    );
}

function ArtworkDetails({ artwork }: { artwork: MetadataRecord }) {
    const counts = asRecord(artwork.counts);
    const missing = asStringArray(artwork.missing_core);
    const artworkStatus = asString(artwork.status) || 'unknown';
    const artworkError = asString(artwork.error);
    const entries = Object.entries(counts)
        .filter(([, value]) => Number(value) > 0)
        .slice(0, 8);
    const tone = artworkStatus === 'failed'
        ? 'danger'
        : missing.length > 0 || artworkStatus === 'empty'
            ? 'warn'
            : 'normal';

    return (
        <div className="space-y-1">
            <PlanLine
                label="artwork"
                value={`${artworkStatus} · ${Number(artwork.total || 0)} files`}
                tone={tone}
            />
            {missing.length > 0 && (
                <PlanLine label="missing" value={missing.join(', ')} tone="warn" />
            )}
            {artworkError && (
                <PlanLine label="error" value={artworkError} tone="danger" />
            )}
            {entries.map(([key, value]) => (
                <PlanLine key={`artwork-${key}`} label={key} value={`${Number(value)} files`} tone="muted" />
            ))}
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

function TaskRow({ task, isPlanOpen, onExecute, onStop, onRollback, onTogglePlan }: { task: Task, isPlanOpen: boolean, onExecute: (t: Task, overrides?: Partial<Pick<Task, 'tmdbId' | 'mediaType'>>) => void, onStop: () => void, onRollback: (t: Task) => void, onTogglePlan: (t: Task) => void }) {
    const isAuditReady = (task.status === 'dry_run' || task.status === 'audit_completed');
    const isRunning = task.status === 'processing' || task.status === 'searching' || task.status === 'fetching';
    const isFinished = task.status === 'completed';
    const isFailed = task.status === 'failed' || task.status === 'partial' || task.status === 'stopped';

    const yearMatch = task.name.match(/\((\d{4})\)/);
    const displayYear = yearMatch ? yearMatch[1] : "—";
    const fileName = task.fullPath ? task.fullPath.split('/').pop() : task.name;
    const planSummary = task.planSummary || task.plan?.summary;
    const canRollback = !!task.taskId && !!task.rollbackAvailable && (isFinished || isFailed) && task.rollback?.status !== 'completed';

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
                    task.status === 'partial' ? "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-400" :
                        isFailed ? "bg-red-100 text-red-500 dark:bg-red-500/10" :
                            isRunning ? "bg-blue-100 text-blue-500 dark:bg-blue-500/10 animate-pulse" :
                                isAuditReady ? "bg-sky-100 text-sky-600 dark:bg-sky-500/10 dark:text-sky-400" :
                                    "bg-slate-100 text-slate-500 dark:bg-slate-800"
                )}>
                    {task.status === 'dry_run' || task.status === 'audit_completed' ? 'PASS' :
                        task.status === 'completed' ? 'Done' :
                            task.status === 'partial' ? 'Partial' :
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
                    <div className="grid grid-cols-5 gap-1 text-[9px] font-mono">
                        <span>{planSummary.actions || 0} act</span>
                        <span className={(planSummary.conflicts || 0) > 0 ? "text-red-500" : "text-[var(--text-muted)]"}>{planSummary.conflicts || 0} cf</span>
                        <span className={(planSummary.risks || 0) > 0 ? "text-amber-500" : "text-[var(--text-muted)]"}>{planSummary.risks || 0} risk</span>
                        <span className={(planSummary.missing_episodes || 0) > 0 ? "text-amber-500" : "text-[var(--text-muted)]"}>{planSummary.missing_episodes || 0} miss</span>
                        <span>{planSummary.metadata_writes || 0} meta</span>
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
                            disabled={(planSummary?.conflicts || 0) > 0 || (planSummary?.blocked || 0) > 0}
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
                    {(task.plan || task.match || task.artwork || task.issue || task.lock || task.rollback) && (
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
                    {isFailed && (
                        <button
                            onClick={() => onExecute(task)}
                            className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all bg-blue-500 text-white hover:bg-blue-600 shadow-sm"
                        >
                            <RotateCcw size={10} />
                            <span>RETRY</span>
                        </button>
                    )}
                    {isFinished && (
                        <button disabled className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider bg-slate-100 dark:bg-white/5 text-slate-400 dark:text-slate-600 cursor-not-allowed">
                            <CheckCircle2 size={10} />
                            <span>Done</span>
                        </button>
                    )}
                    {canRollback && (
                        <button
                            onClick={() => onRollback(task)}
                            className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-colors bg-slate-100 dark:bg-white/10 text-[var(--text-main)] hover:bg-slate-200 dark:hover:bg-white/15 shadow-sm"
                            title="Rollback"
                        >
                            <Undo2 size={10} />
                            <span>ROLLBACK</span>
                        </button>
                    )}
                    {task.rollback?.status === 'completed' && (
                        <span className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
                            <Undo2 size={10} />
                            <span>ROLLED BACK</span>
                        </span>
                    )}
                </div>
            </td>
        </tr>
        {isPlanOpen && (task.plan || task.match || task.artwork || task.issue || task.lock || task.rollback) && (
            <tr className="border-b border-[var(--border-light)] bg-[var(--bg-inner-panel)]">
                <td colSpan={8} className="px-6 py-3">
                    <DetailsPanel taskId={task.taskId} itemId={task.threadId} config={task.config} issue={task.issue} match={task.match} plan={task.plan} planPath={task.planPath} artwork={task.artwork} rollback={task.rollback} lock={task.lock} />
                </td>
            </tr>
        )}
        {isFailed && (
            <tr className="border-b border-[var(--border-light)] bg-red-500/[0.03]">
                <td colSpan={8} className="px-6 py-3">
                    <ManualRetryPanel task={task} onExecute={onExecute} compact />
                </td>
            </tr>
        )}
        </>
    );
}
