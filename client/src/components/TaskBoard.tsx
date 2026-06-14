import { useState, useEffect, useRef } from 'react';
import {
    CheckCircle2, AlertCircle, RotateCcw,
    LayoutGrid, List, FileVideo, Play, Square,
    Clock, MonitorPlay, ArrowDownAZ, ArrowUp, ArrowDown,
    Activity, Undo2, ChevronDown, FileJson, Trash2, RefreshCw,
    type LucideIcon
} from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/languageContext';
import { toast } from 'sonner';
import { cancelTask, clearCompletedTaskHistory, executeConfirmedPlan, fetchPlanArtifact, fetchTaskManifest, fetchTaskSnapshots, openTaskEventSocket, planTask, previewCompletedTaskHistoryClear, previewRecoveryTask, previewRollbackTask, recoverTask, rollbackTask, stopTasks } from '../lib/taskApi';
import type { ExecutionPlan, MatchExplanation, MetadataRecord, TaskEvent, TaskSnapshot } from '../lib/types';
import {
    asRecord,
    asString,
    asStringArray,
    applyTaskEvent,
    buildTaskStartPayload,
    clearTaskHistoryItems,
    deriveTaskBoardState,
    getTaskViewKey,
    rollbackPreviewConfirmationMessage,
    rollbackResultPresentation,
    planReviewHeadline,
    planReviewItems,
    summarizePlanPreview,
    summarizeManifestOperations,
    taskFromSnapshot,
    taskFromSnapshotItem,
    type TaskExecutionConfig,
    type TaskFilter,
    type TaskSortConfig,
    type TaskViewLabels,
    type TaskViewModel,
} from '../lib/taskViewModel';
import { historyCleanupConfirmationMessage } from '../lib/historyViewModel';

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

        const isConfirmedAuditExecution = task.status === 'dry_run' || task.status === 'audit_completed';
        if (isConfirmedAuditExecution) {
            if (!task.taskId || !task.threadId) {
                toast.error('Audited task is missing its plan identity');
                return;
            }
            try {
                const artifact = await fetchPlanArtifact(task.taskId, task.threadId);
                if (!artifact.plan_digest) {
                    toast.error('This audit predates plan locking. Run a new audit first.');
                    return;
                }
                const summary = artifact.plan?.summary;
                const message = [
                    `Execute the audited plan for ${task.name}?`,
                    `${summary?.actions || 0} actions, ${summary?.metadata_writes || 0} metadata writes, ${summary?.risks || 0} risks.`,
                    `Plan ${artifact.plan_digest.slice(0, 12)} will be locked and filesystem drift will stop execution.`,
                ].join('\n');
                if (!window.confirm(message)) return;

                setTasks(prev => {
                    const activeKey = resolveTaskStateKey(prev, task);
                    return {
                        ...prev,
                        [activeKey]: {
                            ...(prev[activeKey] || task),
                            hasExecuted: true,
                            resultSummary: 'Confirmed plan queued for execution',
                        },
                    };
                });
                const result = await executeConfirmedPlan(task.taskId, task.threadId, artifact.plan_digest);
                toast.success(`Confirmed execution started as ${result.task_id.slice(0, 8)}`);
                return;
            } catch (error) {
                setTasks(prev => {
                    const activeKey = resolveTaskStateKey(prev, task);
                    const existing = prev[activeKey];
                    return existing ? {
                        ...prev,
                        [activeKey]: {
                            ...existing,
                            hasExecuted: false,
                            resultSummary: error instanceof Error ? error.message : 'Confirmed execution failed',
                        },
                    } : prev;
                });
                toast.error(error instanceof Error ? error.message : 'Confirmed execution failed');
                return;
            }
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
            const payload = buildTaskStartPayload(task, defaultConfig, overrides);
            await planTask({ ...payload, dry_run: true });
            toast.success('New locked plan requested');
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

    const handleReplan = async (task: Task) => {
        if (!task.fullPath) {
            toast.error('Task is missing a source path');
            return;
        }
        try {
            const payload = buildTaskStartPayload(task, defaultConfig);
            await planTask({ ...payload, dry_run: true });
            setTasks(prev => {
                const activeKey = resolveTaskStateKey(prev, task);
                const existing = prev[activeKey];
                return existing ? {
                    ...prev,
                    [activeKey]: {
                        ...existing,
                        resultSummary: 'New locked plan requested',
                    },
                } : prev;
            });
            toast.success('New locked plan requested');
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Failed to generate a new plan');
        }
    };

    const handleStop = async (task?: Task) => {
        try {
            if (task?.taskId) {
                await cancelTask(task.taskId);
                setTasks(prev => {
                    const activeKey = resolveTaskStateKey(prev, task);
                    const existing = prev[activeKey];
                    return existing ? {
                        ...prev,
                        [activeKey]: { ...existing, status: 'cancel_requested', step: 'Cancelling', resultSummary: 'Cancellation requested' },
                    } : prev;
                });
            } else {
                await stopTasks();
            }
            toast.info('Cancellation requested');
        } catch (e) {
            console.error("Failed to stop tasks", e);
            toast.error(e instanceof Error ? e.message : 'Failed to cancel task');
        }
    };

    const handleRollback = async (task: Task) => {
        if (!task.taskId) return;
        try {
            const preview = await previewRollbackTask(task.taskId);
            if (!window.confirm(rollbackPreviewConfirmationMessage(preview))) {
                toast.info('Rollback cancelled');
                return;
            }
            const result = await rollbackTask(task.taskId);
            const presentation = rollbackResultPresentation(result);
            if (presentation.completed) toast.success('Rollback completed');
            else if (presentation.status === 'partial') toast.warning(presentation.summary);
            else toast.error(presentation.summary);
            setTasks(prev => {
                const key = resolveTaskStateKey(prev, task);
                const existing = prev[key];
                if (!existing) return prev;
                return {
                    ...prev,
                    [key]: {
                        ...existing,
                        rollback: result,
                        rollbackRiskCount: presentation.riskCount,
                        rollbackAvailable: presentation.completed ? false : existing.rollbackAvailable,
                        step: presentation.step,
                        resultSummary: presentation.summary,
                    },
                };
            });
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Rollback failed');
        }
    };

    const handleRecovery = async (task: Task) => {
        if (!task.taskId) return;
        try {
            const preview = await previewRecoveryTask(task.taskId);
            if (preview.status !== 'ready') {
                toast.error(preview.reason || 'Recovery requires manual review');
                return;
            }
            const operationCount = preview.operations?.length || 0;
            const message = preview.rollback_required
                ? `Safely roll back ${operationCount} recorded operations, then retry this task?`
                : 'No filesystem changes were recorded. Retry this task now?';
            if (!window.confirm(message)) return;
            const result = await recoverTask(task.taskId);
            toast.success(`Recovery started as task ${result.task_id.slice(0, 8)}`);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Recovery failed');
        }
    };

    const handleClearHistory = async () => {
        try {
            const preview = await previewCompletedTaskHistoryClear();
            if (!preview.eligible_count) {
                toast.info(
                    preview.retained_count
                        ? `Nothing can be cleared; ${preview.retained_count} actionable task${preview.retained_count === 1 ? ' is' : 's are'} retained`
                        : 'No finished history is available to clear',
                );
                return;
            }
            if (!window.confirm(historyCleanupConfirmationMessage(preview))) return;
            const result = await clearCompletedTaskHistory();
            setTasks(prev => clearTaskHistoryItems(prev, result.task_ids || []));
            const retained = result.retained_count || 0;
            toast.success(
                retained
                    ? `Cleared ${result.removed || 0}; retained ${retained} actionable task${retained === 1 ? '' : 's'}`
                    : `Cleared ${result.removed || 0} historical tasks`,
            );
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Clear history failed');
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
                            next[`${snapshot.id}:${itemId}`] = taskFromSnapshotItem(snapshot, itemId, item, taskLabels);
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

                    <button
                        type="button"
                        disabled={doneOnlyCount + failedCount === 0}
                        onClick={handleClearHistory}
                        className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--border-light)] bg-[var(--bg-toggle-wrapper)] text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-hover)] hover:text-red-500 disabled:opacity-35 disabled:cursor-not-allowed"
                        title="Clear finished task history"
                    >
                        <Trash2 size={14} />
                    </button>
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
                                                    onReplan={handleReplan}
                                                    onStop={handleStop}
                                                    onRollback={handleRollback}
                                                    onRecover={handleRecovery}
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
                                    <TaskCard key={getTaskViewKey(task)} task={task} onExecute={handleExecute} onReplan={handleReplan} onStop={handleStop} onRollback={handleRollback} onRecover={handleRecovery} isPlanOpen={!!expandedPlans[getTaskViewKey(task)]} onTogglePlan={togglePlan} />
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}

function TaskCard({ task, onExecute, onReplan, onStop, onRollback, onRecover, isPlanOpen, onTogglePlan }: { task: Task, onExecute: (t: Task, overrides?: Partial<Pick<Task, 'tmdbId' | 'mediaType'>>) => void, onReplan: (t: Task) => void, onStop: (t: Task) => void, onRollback: (t: Task) => void, onRecover: (t: Task) => void, isPlanOpen: boolean, onTogglePlan: (t: Task) => void }) {
    const isAuditReady = (task.status === 'dry_run' || task.status === 'audit_completed');
    const isRunning = task.status === 'processing' || task.status === 'searching' || task.status === 'fetching' || task.status === 'verifying';
    const isFinished = task.status === 'completed';
    const isFailed = task.status === 'failed' || task.status === 'partial' || task.status === 'stopped';
    const isQuarantined = task.status === 'quarantined';
    const isCancelling = task.status === 'cancel_requested';
    const isCancelled = task.status === 'cancelled';

    const yearMatch = task.name.match(/\((\d{4})\)/);
    const displayYear = yearMatch ? yearMatch[1] : null;
    const cleanTitle = task.name.replace(/\(\d{4}\)/, '').trim() || "Unknown";

    const getStatusInfo = (s: string) => {
        switch (s) {
            case 'completed': return { color: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400', label: 'Done' };
            case 'partial': return { color: 'bg-amber-500/10 text-amber-600 dark:text-amber-400', label: 'Partial' };
            case 'failed': return { color: 'bg-red-500/10 text-red-600 dark:text-red-400', label: 'Failed' };
            case 'stopped': return { color: 'bg-slate-500/10 text-slate-500', label: 'Stopped' };
            case 'quarantined': return { color: 'bg-amber-500/10 text-amber-600 dark:text-amber-400', label: 'Needs naming' };
            case 'cancel_requested': return { color: 'bg-amber-500/10 text-amber-600 dark:text-amber-400 animate-pulse', label: 'Cancelling' };
            case 'cancelled': return { color: 'bg-slate-500/10 text-slate-500', label: 'Cancelled' };
            case 'processing':
            case 'fetching':
            case 'searching': return { color: 'bg-blue-500/10 text-blue-600 dark:text-blue-400 animate-pulse', label: 'Running' };
            case 'verifying': return { color: 'bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 animate-pulse', label: 'Verifying' };
            case 'dry_run':
            case 'audit_completed': return { color: 'bg-sky-500/10 text-sky-600 dark:text-sky-400', label: 'READY' };
            default: return { color: 'bg-slate-500/10 text-slate-500', label: 'Idle' };
        }
    };

    const fileName = task.fullPath ? task.fullPath.split('/').pop() : task.name;
    const plan = task.plan;
    const planSummary = task.planSummary || plan?.summary;
    const hasPlanBlockers = (planSummary?.conflicts || 0) > 0 || (planSummary?.blocked || 0) > 0;
    const statusInfo = hasPlanBlockers && isAuditReady
        ? { color: 'bg-red-500/10 text-red-600 dark:text-red-400', label: 'REVIEW' }
        : getStatusInfo(task.status);
    const hasLockedPlan = !!task.planDigest;
    const match = task.match;
    const canRollback = !!task.taskId && !!task.rollbackAvailable && (isFinished || isFailed) && task.rollback?.status !== 'completed';
    const canRecover = !!task.taskId && isFailed && task.recovery?.status !== 'restarted';

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
                            {(isFinished || isFailed || isAuditReady || isQuarantined) ? task.name : cleanTitle}
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

            {(planSummary || match || task.artwork || task.verification || task.issue || task.lock || task.rollback || task.rollbackAvailable || (task.outputPath && !isQuarantined)) && (
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
                        <DetailsPanel taskId={task.taskId} itemId={task.threadId} config={task.config} issue={task.issue} match={match} plan={plan} planPath={task.planPath} outputPath={task.outputPath} artwork={task.artwork} verification={task.verification} nfoOutputs={task.nfoOutputs} rollback={task.rollback} rollbackRiskCount={task.rollbackRiskCount} lock={task.lock} />
                    )}
                </div>
            )}

            {isAuditReady && hasPlanBlockers && (
                <PlanReviewBanner
                    plan={plan}
                    onReview={() => {
                        if (!isPlanOpen) onTogglePlan(task);
                    }}
                    onReplan={() => onReplan(task)}
                />
            )}

            {isAuditReady && !hasPlanBlockers && (
                <div className="flex items-center justify-between gap-2 rounded-md border border-sky-500/20 bg-sky-500/[0.06] px-2 py-1.5 text-[10px]">
                    <span className="font-bold uppercase tracking-wider text-sky-700 dark:text-sky-300">
                        {hasLockedPlan ? 'Ready to execute' : 'New plan required'}
                    </span>
                    <span className="font-mono text-[var(--text-muted)]">
                        {task.planDigest ? task.planDigest.slice(0, 12) : 'legacy plan · replan required'}
                    </span>
                </div>
            )}

            {!isQuarantined && (task.outputPath || plan?.target_root) && (
                <div className="text-[10px] font-mono text-[var(--text-muted)] truncate rounded-md bg-black/[0.03] dark:bg-white/[0.04] px-2 py-1.5" title={task.outputPath || plan?.target_root}>
                    {plan?.mode || 'target'} → {(task.outputPath || plan?.target_root || '').split('/').pop() || task.outputPath || plan?.target_root}
                </div>
            )}

            {isFailed && (
                <ManualRetryPanel task={task} onExecute={onExecute} />
            )}
            {canRecover && (
                <button
                    type="button"
                    onClick={() => onRecover(task)}
                    className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-cyan-500/30 bg-cyan-500/10 px-3 text-[10px] font-bold uppercase tracking-wider text-cyan-700 hover:bg-cyan-500/15 dark:text-cyan-300"
                    title="Inspect filesystem evidence, roll back safely if needed, then retry"
                >
                    <RefreshCw size={12} />
                    Safe Recover
                </button>
            )}

            {isQuarantined && (
                <div className="rounded-md border border-amber-500/20 bg-amber-500/[0.05] px-2 py-2 text-[10px] leading-relaxed text-amber-700 dark:text-amber-300">
                    Rename this file with a stable title, year, or episode marker, then scan again. No search or file operation was performed.
                </div>
            )}

            <div className="flex flex-col gap-2 pt-2 border-t border-slate-100 dark:border-white/5 mt-auto">
                <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0 flex-1">
                        <div className="text-[10px] font-mono text-[var(--text-muted)] truncate opacity-70 group-hover:opacity-100 transition-opacity" title={task.fullPath}>
                            {fileName}
                        </div>
                    </div>

                    {isAuditReady && !isRunning && !isFinished && !hasPlanBlockers && (
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                if (hasLockedPlan) onExecute(task);
                                else onReplan(task);
                            }}
                            className={cn(
                                "relative z-10 shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider transition-colors shadow-sm",
                                !hasLockedPlan
                                        ? "bg-slate-500/10 text-slate-500 hover:bg-slate-500/15"
                                        : "bg-yellow-400 text-black hover:bg-yellow-300"
                            )}
                            title={!hasLockedPlan ? "Run a new audit to create a locked plan" : "Confirm and execute this locked plan"}
                        >
                            <Play size={10} fill="currentColor" className="text-white" />
                            <span className={hasLockedPlan ? "text-white" : "text-slate-500"}>
                                {hasLockedPlan ? "EXECUTE" : "REPLAN"}
                            </span>
                        </button>
                    )}

                    {isRunning && !isCancelling && (
                        <button
                            onClick={(e) => { e.stopPropagation(); onStop(task); }}
                            className="relative z-10 shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider transition-colors bg-red-500 text-white hover:bg-red-600 shadow-sm animate-pulse"
                        >
                            <Square size={10} fill="currentColor" />
                            <span>STOP</span>
                        </button>
                    )}

                    {isCancelling && (
                        <span className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider bg-amber-500/10 text-amber-600 dark:text-amber-400">
                            <Square size={10} />
                            <span>CANCELLING</span>
                        </span>
                    )}

                    {isCancelled && (
                        <span className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider bg-slate-500/10 text-slate-500">
                            <Square size={10} />
                            <span>CANCELLED</span>
                        </span>
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
                            isActive ? "text-white" : "text-text-muted hover:text-text-main"
                        )}
                        title={opt.label}
                    >
                        {isActive && (
                            <motion.div
                                layoutId={`segment-board-${options[0].value}`}
                                className="absolute inset-0 rounded-md border border-[var(--primary)] bg-[var(--primary)] shadow-sm"
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

function DetailsPanel({ taskId, itemId, config, issue, match, plan, planPath, outputPath, artwork, verification, nfoOutputs, rollback, rollbackRiskCount, lock }: { taskId?: string, itemId?: string, config?: MetadataRecord, issue?: MetadataRecord, match?: MatchExplanation, plan?: ExecutionPlan, planPath?: string, outputPath?: string, artwork?: MetadataRecord, verification?: MetadataRecord, nfoOutputs?: MetadataRecord[], rollback?: MetadataRecord, rollbackRiskCount?: number, lock?: MetadataRecord }) {
    return (
        <div className="border-t border-[var(--border-light)] px-2 py-2 space-y-3">
            {issue && <IssueDetails issue={issue} />}
            {config && <TaskConfigDetails config={config} />}
            {match && <MatchDetails match={match} />}
            {plan && <PlanDetails plan={plan} planPath={planPath} outputPath={outputPath} taskId={taskId} itemId={itemId} />}
            {taskId && <ManifestDetails taskId={taskId} />}
            {lock && <LockDetails lock={lock} />}
            {artwork && <ArtworkDetails artwork={artwork} />}
            {verification && <VerificationDetails verification={verification} />}
            {!!nfoOutputs?.length && <NfoOutputDetails outputs={nfoOutputs} />}
            {rollback && <RollbackDetails rollback={rollback} riskCount={rollbackRiskCount} />}
        </div>
    );
}

function NfoOutputDetails({ outputs }: { outputs: MetadataRecord[] }) {
    const latest = outputs.slice(-5).reverse();
    return (
        <div className="space-y-1">
            <PlanLine label="nfo written" value={`${outputs.length} atomic output${outputs.length === 1 ? '' : 's'}`} tone="normal" />
            {latest.map((output, index) => (
                <PlanLine
                    key={`${asString(output.path) || 'nfo'}-${index}`}
                    label={asString(output.kind) || 'nfo'}
                    value={compactPath(asString(output.path) || '')}
                    tone="muted"
                />
            ))}
        </div>
    );
}

function ManifestDetails({ taskId }: { taskId: string }) {
    const [manifest, setManifest] = useState<MetadataRecord | null>(null);
    const [loading, setLoading] = useState(false);
    const summary = manifest ? summarizeManifestOperations(manifest) : undefined;

    const loadManifest = async () => {
        if (loading) return;
        setLoading(true);
        try {
            const data = await fetchTaskManifest(taskId);
            setManifest(data);
            toast.success('Manifest loaded');
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Manifest unavailable');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="space-y-1">
            <div className="grid grid-cols-[74px_1fr_auto] gap-2 text-[10px] font-mono items-center">
                <span className="truncate uppercase text-[var(--text-dim)]">manifest</span>
                <span className="truncate text-[var(--text-muted)]">
                    {summary ? `${summary.total} ops · ${summary.reversible} reversible${summary.review ? ` · ${summary.review} review` : ''}` : 'rollback evidence'}
                </span>
                <button
                    type="button"
                    disabled={loading}
                    onClick={loadManifest}
                    className="inline-flex h-6 w-6 items-center justify-center rounded-md border border-[var(--border-light)] text-[var(--text-muted)] hover:text-[var(--text-main)] hover:bg-[var(--bg-hover)] disabled:opacity-40 disabled:cursor-not-allowed"
                    title="Load manifest"
                >
                    <FileJson size={12} />
                </button>
            </div>
            {summary && Object.entries(summary.counts).slice(0, 5).map(([action, count]) => (
                <PlanLine key={`manifest-${action}`} label={action} value={`${count} operations`} tone="muted" />
            ))}
            {summary && summary.preview.map((operation, index) => {
                const warningStatuses = new Set(['missing_destination', 'dir_not_empty', 'missing_backup', 'current_modified', 'failed', 'error']);
                const path = operation.destination || operation.source || '';
                return (
                    <PlanLine
                        key={`manifest-op-${index}`}
                        label={`${operation.action}${operation.status ? ` · ${operation.status}` : ''}`}
                        value={compactPath(path)}
                        tone={warningStatuses.has(operation.status) ? 'warn' : 'muted'}
                    />
                );
            })}
            {summary && summary.omitted > 0 && (
                <PlanLine label="more" value={`${summary.omitted} manifest operations omitted from preview`} tone="muted" />
            )}
        </div>
    );
}

function IssueDetails({ issue }: { issue: MetadataRecord }) {
    const status = asString(issue.status) || 'issue';
    const error = asString(issue.error);
    const result = asString(issue.result);
    const reason = asString(issue.reason);
    const path = asString(issue.path);
    const name = asString(issue.name);
    const parse = asRecord(issue.parse);
    const parseConfidence = asString(parse.confidence);
    const parseReasons = Array.isArray(parse.reasons) ? parse.reasons.filter((item): item is string => typeof item === 'string') : [];
    return (
        <div className="space-y-1">
            <PlanLine label={status} value={error || result || reason || name || 'Needs attention'} tone={error ? 'danger' : 'warn'} />
            {parseConfidence && <PlanLine label="parse" value={`${parseConfidence}${parseReasons.length ? ` · ${parseReasons.join(', ')}` : ''}`} tone="warn" />}
            {path && <PlanLine label="path" value={compactPath(path)} tone="muted" />}
        </div>
    );
}

function TaskConfigDetails({ config }: { config: MetadataRecord }) {
    const strategy = asString(config.strategy) || (config.dry_run ? 'audit' : 'organize');
    const operationScope = asString(config.operation_scope) || 'full';
    const conflictStrategy = asString(config.conflict_strategy) || 'error';
    const mediaType = asString(config.media_type) || 'auto';
    const multiMode = config.multi_mode === undefined || config.multi_mode === null ? 'auto' : (config.multi_mode ? 'batch' : 'single');
    return (
        <div className="space-y-1">
            <PlanLine label="config" value={`${strategy} · ${operationScope} · ${asString(config.search_mode) || 'smart'} · ${mediaType} · ${multiMode}`} tone="muted" />
            <PlanLine label="options" value={`${Number(config.workers || 1)} workers · conflicts ${conflictStrategy} · extra ${config.extra_images ? 'on' : 'off'} · organize ${config.enable_organize ? 'on' : 'off'}`} tone="muted" />
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

function PlanDetails({ plan, planPath, outputPath, taskId, itemId }: { plan: ExecutionPlan, planPath?: string, outputPath?: string, taskId?: string, itemId?: string }) {
    const [loadedPlan, setLoadedPlan] = useState<ExecutionPlan | null>(null);
    const [artifactSummary, setArtifactSummary] = useState<string | null>(null);
    const [loadingArtifact, setLoadingArtifact] = useState(false);
    const displayPlan = loadedPlan || plan;
    const actions = (displayPlan.actions || []).slice(0, 8);
    const conflicts = (displayPlan.conflicts || []).slice(0, 5);
    const risks = (displayPlan.risks || []).slice(0, 5);
    const reviewItems = planReviewItems(displayPlan);
    const targetRoot = outputPath || displayPlan.target_root;
    const mode = displayPlan.mode || 'metadata';
    const rollbackLabel = displayPlan.rollback_available ? 'rollback ready' : 'no reversible changes';
    const preview = summarizePlanPreview(plan);
    const canLoad = !!taskId && !!itemId && !!planPath;

    const loadArtifact = async () => {
        if (!canLoad || loadingArtifact) return;
        setLoadingArtifact(true);
        try {
            const artifact = await fetchPlanArtifact(taskId!, itemId!);
            const fullPlan = artifact.plan;
            const actionCount = fullPlan?.summary?.actions ?? fullPlan?.actions?.length ?? 0;
            const generated = artifact?.generated_at ? new Date(artifact.generated_at).toLocaleString() : 'loaded';
            if (fullPlan) setLoadedPlan(fullPlan);
            setArtifactSummary(`${actionCount} actions · ${generated}`);
            toast.success('Full plan loaded');
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Plan artifact unavailable');
        } finally {
            setLoadingArtifact(false);
        }
    };

    return (
        <div className="space-y-2">
            <div className="space-y-1">
                {targetRoot && <PlanLine label="target" value={compactPath(targetRoot)} tone="normal" />}
                <PlanLine label="mode" value={`${mode} · ${displayPlan.operation_scope || 'full'} · conflicts ${displayPlan.conflict_strategy || 'error'} · ${rollbackLabel}`} tone={plan.rollback_available ? 'normal' : 'muted'} />
                {plan.artwork && (
                    <PlanLine
                        label="artwork"
                        value={`extra ${plan.artwork.extra_images ? 'on' : 'off'} · overwrite ${plan.artwork.overwrite_images ? 'on' : 'off'}`}
                        tone="muted"
                    />
                )}
                {displayPlan.nfo && (
                    <PlanLine
                        label="nfo"
                        value={`${asString(asRecord(displayPlan.nfo.policy).profile) || 'universal'} · present episodes only · ${Number(displayPlan.nfo.present_episodes || 0)} local`}
                        tone="muted"
                    />
                )}
            </div>
            {planPath && (
                <div className="space-y-1">
                    <div className="grid grid-cols-[74px_1fr_auto] gap-2 text-[10px] font-mono items-center">
                        <span className="truncate uppercase text-[var(--text-dim)]">artifact</span>
                        <span className="truncate text-[var(--text-muted)]" title={artifactSummary || planPath}>
                            {artifactSummary || (loadedPlan ? 'full plan loaded' : planPath)}
                        </span>
                        <button
                            type="button"
                            disabled={!canLoad || loadingArtifact}
                            onClick={loadArtifact}
                            className="inline-flex h-6 w-6 items-center justify-center rounded-md border border-[var(--border-light)] text-[var(--text-muted)] hover:text-[var(--text-main)] hover:bg-[var(--bg-hover)] disabled:opacity-40 disabled:cursor-not-allowed"
                            title="Load full plan"
                        >
                            <FileJson size={12} />
                        </button>
                    </div>
                    {!loadedPlan && preview.hasHiddenPreview && (
                        <PlanLine
                            label="preview"
                            value={`compact · hidden ${preview.hiddenActions} actions, ${preview.hiddenRisks} risks, ${preview.hiddenConflicts} conflicts`}
                            tone={preview.hiddenConflicts > 0 ? 'danger' : preview.hiddenRisks > 0 ? 'warn' : 'muted'}
                        />
                    )}
                </div>
            )}
            {reviewItems.length > 0 && (
                <div className="space-y-1 rounded-md border border-red-500/25 bg-red-500/[0.05] p-2">
                    <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-red-600 dark:text-red-400">
                        <AlertCircle size={12} />
                        Manual review required
                    </div>
                    {reviewItems.slice(0, 5).map((item, index) => (
                        <div key={`review-${item.code}-${index}`} className="space-y-1 border-t border-red-500/15 pt-1.5 first:border-0 first:pt-0">
                            <PlanLine label={item.episode || item.code} value={item.message} tone="danger" />
                            <PlanLine label="fix" value={item.guidance} tone="warn" />
                            {item.sources.slice(0, 4).map((source, sourceIndex) => (
                                <PlanLine key={`review-source-${sourceIndex}`} label={sourceIndex === 0 ? 'files' : ''} value={compactPath(source)} tone="muted" />
                            ))}
                            {item.destination && <PlanLine label="target" value={compactPath(item.destination)} tone="muted" />}
                        </div>
                    ))}
                </div>
            )}
            {conflicts.length > 0 && (
                <div className="space-y-1">
                    {conflicts.map((item, index) => (
                        <PlanLine
                            key={`conflict-${index}`}
                            tone={asString(item.resolution) === 'blocked' ? 'danger' : 'warn'}
                            label={`${asString(item.reason) || 'conflict'} · ${asString(item.resolution) || 'review'}`}
                            value={asString(item.resolved_destination) || asString(item.destination) || asString(item.source) || ''}
                        />
                    ))}
                </div>
            )}
            {risks.length > 0 && (
                <div className="space-y-1">
                    {risks.map((item, index) => (
                        <PlanLine key={`risk-${index}`} tone={item.level === 'error' ? 'danger' : item.level === 'warning' ? 'warn' : 'normal'} label={asString(item.code) || asString(item.level) || 'risk'} value={asString(item.message) || ''} />
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

function PlanReviewBanner({ plan, onReview, onReplan }: { plan?: ExecutionPlan, onReview: () => void, onReplan: () => void }) {
    return (
        <div className="rounded-md border border-red-500/25 bg-red-500/[0.06] p-2">
            <div className="flex items-start gap-2">
                <AlertCircle size={15} className="mt-0.5 shrink-0 text-red-500" />
                <div className="min-w-0 flex-1">
                    <div className="text-[10px] font-bold uppercase tracking-wider text-red-600 dark:text-red-400">
                        Manual review required
                    </div>
                    <div className="mt-0.5 text-[10px] leading-relaxed text-[var(--text-muted)]">
                        {planReviewHeadline(plan)}
                    </div>
                </div>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2">
                <button
                    type="button"
                    onClick={onReview}
                    className="inline-flex h-7 items-center justify-center gap-1.5 rounded-md border border-red-500/25 bg-red-500/10 px-2 text-[9px] font-bold uppercase tracking-wider text-red-600 hover:bg-red-500/15 dark:text-red-300"
                >
                    <AlertCircle size={11} />
                    Review
                </button>
                <button
                    type="button"
                    onClick={onReplan}
                    className="inline-flex h-7 items-center justify-center gap-1.5 rounded-md border border-[var(--border-light)] bg-[var(--bg-panel)] px-2 text-[9px] font-bold uppercase tracking-wider text-[var(--text-main)] hover:bg-[var(--bg-hover)]"
                    title="Generate a new locked plan after correcting the files"
                >
                    <RefreshCw size={11} />
                    Replan
                </button>
            </div>
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

function RollbackDetails({ rollback, riskCount = 0 }: { rollback: MetadataRecord, riskCount?: number }) {
    const operations = Array.isArray(rollback.operations) ? rollback.operations.slice(0, 5) : [];
    const rollbackStatus = asString(rollback.status) || 'unknown';
    const describeRollbackStatus = (status?: string) => {
        if (status === 'current_modified') return 'changed after task';
        if (status === 'dir_not_empty') return 'directory not empty';
        if (status === 'missing_backup') return 'backup missing';
        if (status === 'missing_destination') return 'already missing';
        return status || 'op';
    };
    return (
        <div className="space-y-1">
            <PlanLine
                label="rollback"
                value={`${rollbackStatus}${operations.length ? ` · ${operations.length} ops` : ''}${riskCount ? ` · ${riskCount} review` : ''}`}
                tone={rollbackStatus === 'completed' && riskCount === 0 ? 'normal' : rollbackStatus === 'failed' ? 'danger' : 'warn'}
            />
            {operations.map((item, index: number) => {
                const operation = asRecord(item);
                const operationStatus = asString(operation.status);
                const warningStatuses = new Set(['missing_destination', 'dir_not_empty', 'missing_backup', 'current_modified']);
                return (
                <PlanLine
                    key={`rollback-${index}`}
                    label={describeRollbackStatus(operationStatus)}
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

function VerificationDetails({ verification }: { verification: MetadataRecord }) {
    const status = asString(verification.status) || 'unknown';
    const checks = Array.isArray(verification.checks) ? verification.checks.map(asRecord) : [];
    const problemChecks = checks.filter((check) => asString(check.status) !== 'passed').slice(0, 6);
    const tone = status === 'failed' ? 'danger' : status === 'partial' ? 'warn' : 'normal';
    return (
        <div className="space-y-1">
            <PlanLine
                label="verification"
                value={`${status} · ${Number(verification.passed || 0)}/${Number(verification.checked || 0)} passed · ${Number(verification.warnings || 0)} warnings${Number(verification.skipped || 0) ? ` · ${Number(verification.skipped)} optional` : ''}`}
                tone={tone}
            />
            {problemChecks.map((check, index) => (
                <PlanLine
                    key={`verification-${asString(check.code) || index}-${index}`}
                    label={asString(check.code) || 'check'}
                    value={asString(check.message) || compactPath(asString(check.destination) || '')}
                    tone={asString(check.status) === 'failed' ? 'danger' : 'warn'}
                />
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

function TaskRow({ task, isPlanOpen, onExecute, onReplan, onStop, onRollback, onRecover, onTogglePlan }: { task: Task, isPlanOpen: boolean, onExecute: (t: Task, overrides?: Partial<Pick<Task, 'tmdbId' | 'mediaType'>>) => void, onReplan: (t: Task) => void, onStop: (t: Task) => void, onRollback: (t: Task) => void, onRecover: (t: Task) => void, onTogglePlan: (t: Task) => void }) {
    const isAuditReady = (task.status === 'dry_run' || task.status === 'audit_completed');
    const isRunning = task.status === 'processing' || task.status === 'searching' || task.status === 'fetching' || task.status === 'verifying';
    const isFinished = task.status === 'completed';
    const isFailed = task.status === 'failed' || task.status === 'partial' || task.status === 'stopped';
    const isQuarantined = task.status === 'quarantined';
    const isCancelling = task.status === 'cancel_requested';
    const isCancelled = task.status === 'cancelled';

    const yearMatch = task.name.match(/\((\d{4})\)/);
    const displayYear = yearMatch ? yearMatch[1] : "—";
    const fileName = task.fullPath ? task.fullPath.split('/').pop() : task.name;
    const planSummary = task.planSummary || task.plan?.summary;
    const hasPlanBlockers = (planSummary?.conflicts || 0) > 0 || (planSummary?.blocked || 0) > 0;
    const hasLockedPlan = !!task.planDigest;
    const canRollback = !!task.taskId && !!task.rollbackAvailable && (isFinished || isFailed) && task.rollback?.status !== 'completed';
    const canRecover = !!task.taskId && isFailed && task.recovery?.status !== 'restarted';

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
                            isQuarantined ? "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-400" :
                            isCancelling ? "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-400 animate-pulse" :
                            isCancelled ? "bg-slate-100 text-slate-500 dark:bg-slate-800" :
                            isRunning ? "bg-blue-100 text-blue-500 dark:bg-blue-500/10 animate-pulse" :
                                isAuditReady && hasPlanBlockers ? "bg-red-100 text-red-600 dark:bg-red-500/10 dark:text-red-400" :
                                isAuditReady ? "bg-sky-100 text-sky-600 dark:bg-sky-500/10 dark:text-sky-400" :
                                    "bg-slate-100 text-slate-500 dark:bg-slate-800"
                )}>
                    {isAuditReady && hasPlanBlockers ? 'REVIEW' :
                        task.status === 'dry_run' || task.status === 'audit_completed' ? 'READY' :
                        task.status === 'completed' ? 'Done' :
                            task.status === 'partial' ? 'Partial' :
                            task.status === 'stopped' ? 'Stopped' :
                            task.status === 'quarantined' ? 'Needs naming' :
                            task.status === 'cancel_requested' ? 'Cancelling' :
                            task.status === 'cancelled' ? 'Cancelled' :
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
                ) : (task.resultSummary || (isFinished || isFailed || isAuditReady || isQuarantined)) && (
                    <div className={cn("flex items-center justify-center gap-1.5 font-medium truncate",
                        (isFinished || isAuditReady) ? "text-emerald-600 dark:text-emerald-400" :
                            isQuarantined ? "text-amber-600 dark:text-amber-400" :
                            isFailed ? "text-red-500 dark:text-red-400" : "text-slate-500"
                    )} title={task.resultSummary || ""}>
                        {(isFinished || isAuditReady) ? <CheckCircle2 size={12} className="shrink-0" /> : (isFailed || isQuarantined) ? <AlertCircle size={12} className="shrink-0" /> : null}
                        <span className="truncate">
                            {task.resultSummary || (isFinished ? "完成" : (isAuditReady ? "匹配到元数据" : (isFailed ? "失败" : "-")))}
                        </span>
                    </div>
                )}
            </td>
            <td className="px-6 py-4 text-center">
                <div className="flex justify-center gap-2">
                    {isAuditReady && !isRunning && !isFinished && hasPlanBlockers && (
                        <>
                            <button
                                onClick={() => {
                                    if (!isPlanOpen) onTogglePlan(task);
                                }}
                                className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider bg-red-500/10 text-red-600 hover:bg-red-500/15 dark:text-red-300"
                            >
                                <AlertCircle size={10} />
                                Review
                            </button>
                            <button
                                onClick={() => onReplan(task)}
                                className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider bg-slate-100 dark:bg-white/10 text-[var(--text-main)] hover:bg-slate-200 dark:hover:bg-white/15"
                            >
                                <RefreshCw size={10} />
                                Replan
                            </button>
                        </>
                    )}
                    {isAuditReady && !isRunning && !isFinished && !hasPlanBlockers && (
                        <button
                            onClick={() => hasLockedPlan ? onExecute(task) : onReplan(task)}
                            className={cn(
                                "shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-colors shadow-sm",
                                !hasLockedPlan
                                        ? "bg-slate-500/10 text-slate-500 hover:bg-slate-500/15"
                                    : "bg-yellow-400 text-black hover:bg-yellow-300"
                            )}
                            title={!hasLockedPlan ? "Run a new audit to create a locked plan" : "Confirm and execute this locked plan"}
                        >
                            <Play size={10} fill="currentColor" className="text-white" />
                            <span className={hasLockedPlan ? "text-white" : "text-slate-500"}>
                                {hasLockedPlan ? "EXECUTE" : "REPLAN"}
                            </span>
                        </button>
                    )}
                    {(task.plan || task.match || task.artwork || task.verification || task.issue || task.lock || task.rollback || task.rollbackAvailable || (task.outputPath && !isQuarantined)) && (
                        <button
                            onClick={() => onTogglePlan(task)}
                            className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-colors bg-slate-100 dark:bg-white/10 text-[var(--text-main)] hover:bg-slate-200 dark:hover:bg-white/15 shadow-sm"
                            title="Details"
                        >
                            <List size={10} />
                            <span>DETAILS</span>
                        </button>
                    )}
                    {isRunning && !isCancelling && (
                        <button
                            onClick={() => onStop(task)}
                            className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all bg-red-500 text-white hover:bg-red-600 shadow-sm"
                        >
                            <Square size={10} fill="currentColor" />
                            <span>STOP</span>
                        </button>
                    )}
                    {isCancelling && <span className="text-[10px] font-bold uppercase text-amber-500">Cancelling</span>}
                    {isCancelled && <span className="text-[10px] font-bold uppercase text-slate-500">Cancelled</span>}
                    {isFailed && (
                        <button
                            onClick={() => onExecute(task)}
                            className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all bg-blue-500 text-white hover:bg-blue-600 shadow-sm"
                        >
                            <RotateCcw size={10} />
                            <span>RETRY</span>
                        </button>
                    )}
                    {canRecover && (
                        <button
                            onClick={() => onRecover(task)}
                            className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider bg-cyan-500/10 text-cyan-700 hover:bg-cyan-500/15 dark:text-cyan-300"
                            title="Safe recovery"
                        >
                            <RefreshCw size={10} />
                            <span>RECOVER</span>
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
        {isPlanOpen && (task.plan || task.match || task.artwork || task.verification || task.issue || task.lock || task.rollback || task.rollbackAvailable || (task.outputPath && !isQuarantined)) && (
            <tr className="border-b border-[var(--border-light)] bg-[var(--bg-inner-panel)]">
                <td colSpan={8} className="px-6 py-3">
                    <DetailsPanel taskId={task.taskId} itemId={task.threadId} config={task.config} issue={task.issue} match={task.match} plan={task.plan} planPath={task.planPath} outputPath={task.outputPath} artwork={task.artwork} verification={task.verification} nfoOutputs={task.nfoOutputs} rollback={task.rollback} rollbackRiskCount={task.rollbackRiskCount} lock={task.lock} />
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
