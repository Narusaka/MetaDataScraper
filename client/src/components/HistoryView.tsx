import { useCallback, useEffect, useMemo, useState } from 'react';
import {
    AlertTriangle,
    CheckCircle2,
    ChevronDown,
    Clock3,
    FileJson,
    Folder,
    History,
    RefreshCw,
    RotateCcw,
    Search,
    ShieldCheck,
    Trash2,
} from 'lucide-react';
import { toast } from 'sonner';

import { cn } from '../lib/utils';
import {
    clearCompletedTaskHistory,
    fetchPlanArtifact,
    fetchTaskHistory,
    fetchTaskManifest,
    previewCompletedTaskHistoryClear,
    previewRecoveryTask,
    previewRollbackTask,
    recoverTask,
    rollbackTask,
} from '../lib/taskApi';
import {
    deriveHistory,
    historyScopeLabel,
    historyCleanupConfirmationMessage,
    historyStats,
    historyStatusLabel,
    historyStrategyLabel,
    historyTone,
    type HistoryFilter,
    type HistoryTone,
} from '../lib/historyViewModel';
import { rollbackPreviewConfirmationMessage, rollbackResultPresentation } from '../lib/taskViewModel';
import type { ExecutionPlan, ManifestResponse, MetadataRecord, TaskSnapshot } from '../lib/types';

interface HistoryViewProps {
    active: boolean;
}

interface HistoryDetails {
    loading?: boolean;
    error?: string;
    manifest?: ManifestResponse;
    plans?: Record<string, ExecutionPlan>;
    loadingPlan?: string;
}

const toneClasses: Record<HistoryTone, string> = {
    success: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-500',
    warning: 'border-amber-500/25 bg-amber-500/10 text-amber-500',
    danger: 'border-red-500/25 bg-red-500/10 text-red-500',
    neutral: 'border-border-light bg-bg-surface text-text-muted',
};

const numberValue = (value: unknown) => typeof value === 'number' ? value : 0;
const stringValue = (value: unknown) => typeof value === 'string' ? value : '';
const recordValue = (value: unknown): MetadataRecord => (
    value && typeof value === 'object' && !Array.isArray(value) ? value as MetadataRecord : {}
);

export function HistoryView({ active }: HistoryViewProps) {
    const [tasks, setTasks] = useState<TaskSnapshot[]>([]);
    const [filter, setFilter] = useState<HistoryFilter>('all');
    const [query, setQuery] = useState('');
    const [loading, setLoading] = useState(false);
    const [expanded, setExpanded] = useState<Record<string, boolean>>({});
    const [details, setDetails] = useState<Record<string, HistoryDetails>>({});
    const [recovering, setRecovering] = useState<string>();

    const loadHistory = useCallback(async () => {
        setLoading(true);
        try {
            const response = await fetchTaskHistory();
            setTasks(response.tasks || []);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Task history unavailable');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (active) void loadHistory();
    }, [active, loadHistory]);

    const stats = useMemo(() => historyStats(tasks), [tasks]);
    const visibleTasks = useMemo(() => deriveHistory(tasks, filter, query), [tasks, filter, query]);

    const toggleDetails = async (task: TaskSnapshot) => {
        const opening = !expanded[task.id];
        setExpanded(current => ({ ...current, [task.id]: opening }));
        if (!opening || details[task.id]?.manifest || details[task.id]?.loading || !task.manifest_summary?.exists) return;

        setDetails(current => ({ ...current, [task.id]: { ...current[task.id], loading: true, error: undefined } }));
        try {
            const manifest = await fetchTaskManifest(task.id);
            setDetails(current => ({ ...current, [task.id]: { ...current[task.id], loading: false, manifest } }));
        } catch (error) {
            setDetails(current => ({
                ...current,
                [task.id]: {
                    ...current[task.id],
                    loading: false,
                    error: error instanceof Error ? error.message : 'Manifest unavailable',
                },
            }));
        }
    };

    const loadPlan = async (taskId: string, itemId: string) => {
        if (details[taskId]?.plans?.[itemId] || details[taskId]?.loadingPlan === itemId) return;
        setDetails(current => ({
            ...current,
            [taskId]: { ...current[taskId], loadingPlan: itemId },
        }));
        try {
            const artifact = await fetchPlanArtifact(taskId, itemId);
            setDetails(current => ({
                ...current,
                [taskId]: {
                    ...current[taskId],
                    loadingPlan: undefined,
                    plans: { ...current[taskId]?.plans, [itemId]: artifact.plan || {} },
                },
            }));
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Plan unavailable');
            setDetails(current => ({
                ...current,
                [taskId]: { ...current[taskId], loadingPlan: undefined },
            }));
        }
    };

    const handleRollback = async (task: TaskSnapshot) => {
        try {
            const preview = await previewRollbackTask(task.id);
            if (!window.confirm(rollbackPreviewConfirmationMessage(preview))) return;
            const result = await rollbackTask(task.id);
            const presentation = rollbackResultPresentation(result);
            setTasks(current => current.map(item => item.id === task.id ? {
                ...item,
                rollback: result,
                rolled_back: presentation.completed,
                rollback_available: presentation.completed ? false : item.rollback_available,
            } : item));
            if (presentation.completed) toast.success('Rollback completed');
            else if (presentation.status === 'partial') toast.warning(presentation.summary);
            else toast.error(presentation.summary);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Rollback failed');
        }
    };

    const handleRecovery = async (task: TaskSnapshot) => {
        setRecovering(task.id);
        try {
            const preview = await previewRecoveryTask(task.id);
            if (preview.status !== 'ready') {
                toast.error(preview.reason || 'Recovery requires manual review');
                return;
            }
            const action = preview.rollback_required
                ? 'roll back recorded changes, then create a new task'
                : 'create a new task from the saved configuration';
            if (!window.confirm(`Recover interrupted task ${task.id.slice(0, 8)}?\n\nThis will ${action}.`)) return;
            const result = await recoverTask(task.id);
            await loadHistory();
            toast.success(`Recovery started as ${result.task_id.slice(0, 8)}`);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Recovery failed');
        } finally {
            setRecovering(undefined);
        }
    };

    const handleClear = async () => {
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
            await loadHistory();
            const retained = result.retained_count || 0;
            const cleanupErrors = result.plan_cleanup_errors?.length || 0;
            if (cleanupErrors) {
                toast.warning(`Cleared ${result.removed || 0}; ${cleanupErrors} plan artifact cleanup failed`);
            } else if (retained) {
                toast.success(`Cleared ${result.removed || 0}; retained ${retained} actionable task${retained === 1 ? '' : 's'}`);
            } else {
                toast.success(`Cleared ${result.removed || 0} history records`);
            }
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Clear history failed');
        }
    };

    return (
        <section className="h-full min-h-0 overflow-hidden rounded-3xl border border-glass-border glass-panel-pro shadow-xl flex flex-col">
            <header className="shrink-0 border-b border-border-light px-6 py-5">
                <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                        <div className="flex items-center gap-2">
                            <History size={18} className="text-primary" />
                            <h2 className="text-lg font-bold text-text-main">History & Rollback</h2>
                        </div>
                        <p className="mt-1 text-xs text-text-muted">Auditable task records backed by execution manifests.</p>
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            type="button"
                            onClick={() => void loadHistory()}
                            disabled={loading}
                            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border-light bg-bg-surface text-text-muted hover:text-primary disabled:opacity-50"
                            title="Refresh history"
                        >
                            <RefreshCw size={15} className={cn(loading && 'animate-spin')} />
                        </button>
                        <button
                            type="button"
                            onClick={handleClear}
                            disabled={tasks.length === 0}
                            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border-light bg-bg-surface text-text-muted hover:text-red-500 disabled:opacity-35"
                            title="Clear finished history"
                        >
                            <Trash2 size={15} />
                        </button>
                    </div>
                </div>

                <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-5">
                    <Metric label="Tasks" value={stats.tasks} icon={History} />
                    <Metric label="Succeeded items" value={stats.completed} icon={CheckCircle2} tone="success" />
                    <Metric label="Failed items" value={stats.failed} icon={AlertTriangle} tone={stats.failed ? 'danger' : 'neutral'} />
                    <Metric label="Recorded changes" value={stats.changes} icon={FileJson} />
                    <Metric label="Rollback ready" value={stats.rollbackReady} icon={ShieldCheck} tone={stats.rollbackReady ? 'warning' : 'neutral'} />
                </div>

                <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                    <div className="flex rounded-lg border border-border-light bg-bg-surface p-1">
                        {([
                            ['all', `All ${stats.tasks}`],
                            ['success', 'Completed'],
                            ['issues', 'Issues'],
                            ['rollback', `Rollback ${stats.rollbackReady}`],
                        ] as Array<[HistoryFilter, string]>).map(([value, label]) => (
                            <button
                                key={value}
                                type="button"
                                onClick={() => setFilter(value)}
                                className={cn(
                                    'h-8 px-3 rounded-md text-[11px] font-semibold transition-colors',
                                    filter === value ? 'bg-primary text-white' : 'text-text-muted hover:text-text-main',
                                )}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                    <label className="flex h-10 min-w-[240px] flex-1 items-center gap-2 rounded-lg border border-border-light bg-bg-surface px-3 lg:max-w-sm">
                        <Search size={14} className="text-text-muted" />
                        <input
                            value={query}
                            onChange={event => setQuery(event.target.value)}
                            placeholder="Search path, task ID, status..."
                            className="min-w-0 flex-1 bg-transparent text-xs outline-none placeholder:text-text-muted/60"
                        />
                    </label>
                </div>
            </header>

            <div className="flex-1 min-h-0 overflow-y-auto">
                {visibleTasks.length === 0 ? (
                    <div className="h-full min-h-[280px] flex flex-col items-center justify-center gap-3 text-text-muted">
                        <History size={30} className="opacity-35" />
                        <p className="text-sm font-semibold">{loading ? 'Loading task history...' : 'No matching history records'}</p>
                    </div>
                ) : (
                    <div className="divide-y divide-border-light">
                        {visibleTasks.map(task => (
                            <HistoryRow
                                key={task.id}
                                task={task}
                                expanded={!!expanded[task.id]}
                                details={details[task.id]}
                                onToggle={() => void toggleDetails(task)}
                                onLoadPlan={(itemId) => void loadPlan(task.id, itemId)}
                                onRollback={() => void handleRollback(task)}
                                recovering={recovering === task.id}
                                onRecover={() => void handleRecovery(task)}
                            />
                        ))}
                    </div>
                )}
            </div>
        </section>
    );
}

function Metric({ label, value, icon: Icon, tone = 'neutral' }: {
    label: string;
    value: number;
    icon: typeof History;
    tone?: HistoryTone;
}) {
    return (
        <div className="min-h-[72px] border-l-2 border-border-light px-3 py-2">
            <div className="flex items-center gap-2 text-[10px] uppercase font-bold tracking-wider text-text-muted">
                <Icon size={13} className={cn(tone === 'success' && 'text-emerald-500', tone === 'warning' && 'text-amber-500', tone === 'danger' && 'text-red-500')} />
                {label}
            </div>
            <div className="mt-2 font-mono text-xl font-bold text-text-main">{value}</div>
        </div>
    );
}

function HistoryRow({ task, expanded, details, recovering, onToggle, onLoadPlan, onRollback, onRecover }: {
    task: TaskSnapshot;
    expanded: boolean;
    details?: HistoryDetails;
    recovering: boolean;
    onToggle: () => void;
    onLoadPlan: (itemId: string) => void;
    onRollback: () => void;
    onRecover: () => void;
}) {
    const summary = task.summary || {};
    const completed = numberValue(summary.completed);
    const failed = numberValue(summary.failed);
    const total = numberValue(summary.total);
    const itemEntries = Object.entries(task.items || {});
    const strategy = historyStrategyLabel(task);
    const scope = historyScopeLabel(task);
    const date = new Date(task.updated_at || task.created_at);
    const manifest = task.manifest_summary;
    const manifestOperations = Array.isArray(details?.manifest?.operations)
        ? details.manifest.operations.map(recordValue).slice(0, 6)
        : [];
    const tone = historyTone(task);

    return (
        <article className="bg-transparent">
            <div className="grid min-h-[92px] grid-cols-[minmax(0,1fr)_auto] items-center gap-4 px-5 py-4 lg:grid-cols-[minmax(280px,1.4fr)_140px_150px_150px_auto]">
                <button type="button" onClick={onToggle} className="min-w-0 text-left">
                    <div className="flex items-center gap-3">
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-bg-surface text-text-muted">
                            <Folder size={16} />
                        </span>
                        <span className="min-w-0">
                            <span className="block truncate text-sm font-semibold text-text-main">{task.input_dir.split('/').pop() || task.input_dir}</span>
                            <span className="mt-1 block truncate font-mono text-[10px] text-text-muted">{task.input_dir}</span>
                            {task.status === 'interrupted' && (
                                <span className="mt-1 block text-[10px] font-medium text-red-500">
                                    Service restarted before this task reported a final result.
                                </span>
                            )}
                        </span>
                    </div>
                </button>

                <div className="hidden lg:block">
                    <div className="flex items-center gap-1.5 text-xs text-text-main"><Clock3 size={12} className="text-text-muted" />{Number.isNaN(date.getTime()) ? 'Unknown' : date.toLocaleDateString()}</div>
                    <div className="mt-1 text-[10px] text-text-muted">{Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString()}</div>
                </div>

                <div className="hidden lg:block text-xs">
                    <div className="font-semibold text-text-main">{completed}/{total || completed + failed} succeeded</div>
                    <div className={cn('mt-1 text-[10px]', failed ? 'text-red-500' : 'text-text-muted')}>{failed} failed · {itemEntries.length} items</div>
                </div>

                <div className="hidden lg:block text-xs">
                    <div className="font-semibold capitalize text-text-main">{strategy} · {scope}</div>
                    <div className="mt-1 text-[10px] text-text-muted">
                        {manifest?.operation_count || 0} changes · {manifest?.reversible_count || 0} reversible
                        {!!manifest?.failed_count && <span className="text-red-500"> · {manifest.failed_count} failed attempts</span>}
                    </div>
                </div>

                <div className="flex items-center justify-end gap-2">
                    <span className={cn('hidden sm:inline-flex h-7 items-center rounded-md border px-2 text-[10px] font-bold uppercase', toneClasses[tone])}>
                        {historyStatusLabel(task)}
                    </span>
                    {task.status === 'interrupted' && (
                        <button
                            type="button"
                            onClick={event => { event.stopPropagation(); onRecover(); }}
                            disabled={recovering}
                            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 px-2.5 text-[10px] font-bold text-blue-500 hover:bg-blue-500/20 disabled:opacity-50"
                            title="Inspect recovery safety and restart from saved configuration"
                        >
                            <RefreshCw size={13} className={cn(recovering && 'animate-spin')} />
                            {recovering ? 'Checking' : 'Recover'}
                        </button>
                    )}
                    {task.rollback_available && (
                        <button
                            type="button"
                            onClick={event => { event.stopPropagation(); onRollback(); }}
                            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 text-[10px] font-bold text-amber-500 hover:bg-amber-500/20"
                            title="Preview and rollback recorded changes"
                        >
                            <RotateCcw size={13} /> Rollback
                        </button>
                    )}
                    <button
                        type="button"
                        onClick={onToggle}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border-light bg-bg-surface text-text-muted"
                        title={expanded ? 'Collapse details' : 'Open task details'}
                    >
                        <ChevronDown size={15} className={cn('transition-transform', expanded && 'rotate-180')} />
                    </button>
                </div>
            </div>

            {expanded && (
                <div className="border-t border-border-light bg-black/[0.025] px-5 py-5 dark:bg-black/10">
                    <div className="grid gap-6 xl:grid-cols-[280px_minmax(0,1fr)]">
                        <div>
                            <h3 className="text-[10px] font-bold uppercase tracking-wider text-text-muted">Execution manifest</h3>
                            {details?.loading ? (
                                <p className="mt-3 text-xs text-text-muted">Loading manifest...</p>
                            ) : details?.error ? (
                                <p className="mt-3 text-xs text-red-500">{details.error}</p>
                            ) : (
                                <div className="mt-3 space-y-2">
                                    <DetailLine label="Task ID" value={task.id} mono />
                                    <DetailLine label="Operations" value={String(manifest?.operation_count || 0)} />
                                    {!!manifest?.failed_count && <DetailLine label="Failed attempts" value={String(manifest.failed_count)} />}
                                    <DetailLine label="Reversible" value={String(manifest?.reversible_count || 0)} />
                                    {Object.entries(manifest?.action_counts || {}).slice(0, 6).map(([action, count]) => (
                                        <DetailLine key={action} label={action.replaceAll('_', ' ')} value={String(count)} />
                                    ))}
                                    {manifest?.error && <p className="pt-2 text-[10px] text-red-500">{manifest.error}</p>}
                                    {!manifest?.exists && <p className="pt-2 text-[10px] text-text-muted">No filesystem manifest was recorded for this task.</p>}
                                    {manifestOperations.length > 0 && (
                                        <div className="pt-3 border-t border-border-light space-y-2">
                                            <div className="text-[9px] uppercase font-bold tracking-wider text-text-muted">Recorded operations</div>
                                            {manifestOperations.map((operation, index) => (
                                                <div key={`${stringValue(operation.action)}-${index}`} className="min-w-0">
                                                    <div className="text-[10px] font-semibold capitalize text-text-main">{(stringValue(operation.action) || 'operation').replaceAll('_', ' ')}</div>
                                                    <div className="truncate font-mono text-[9px] text-text-muted" title={stringValue(operation.destination) || stringValue(operation.source)}>
                                                        {stringValue(operation.destination) || stringValue(operation.source) || 'No path recorded'}
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>

                        <div className="min-w-0">
                            <h3 className="text-[10px] font-bold uppercase tracking-wider text-text-muted">Items & plans</h3>
                            {itemEntries.length === 0 ? (
                                <p className="mt-3 text-xs text-text-muted">No item-level records were persisted.</p>
                            ) : (
                                <div className="mt-3 divide-y divide-border-light border-y border-border-light">
                                    {itemEntries.slice(0, 20).map(([itemId, rawItem]) => {
                                        const item = recordValue(rawItem);
                                        const candidate = recordValue(item.candidate);
                                        const plan = details?.plans?.[itemId];
                                        const planSummary = recordValue(plan?.summary || item.plan_summary);
                                        const verification = recordValue(item.verification);
                                        const hasPlan = !!stringValue(item.plan_path) || !!item.plan;
                                        const itemStatus = stringValue(item.status);
                                        const itemReason = stringValue(item.reason);
                                        return (
                                            <div key={itemId} className="py-3">
                                                <div className="flex flex-wrap items-center justify-between gap-3">
                                                    <div className="min-w-0">
                                                        <div className="flex min-w-0 items-center gap-2">
                                                            <div className="truncate text-xs font-semibold text-text-main">{stringValue(candidate.title) || stringValue(item.name) || itemId.split('/').pop()}</div>
                                                            {itemStatus === 'quarantined' && (
                                                                <span className="shrink-0 rounded-md bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase text-amber-600 dark:text-amber-400">Needs naming</span>
                                                            )}
                                                        </div>
                                                        <div className="mt-1 truncate font-mono text-[9px] text-text-muted">{stringValue(item.path) || itemId}</div>
                                                        {itemReason && <div className="mt-1 text-[10px] text-amber-600 dark:text-amber-400">{itemReason}</div>}
                                                    </div>
                                                    {hasPlan && (
                                                        <button
                                                            type="button"
                                                            onClick={() => onLoadPlan(itemId)}
                                                            disabled={details?.loadingPlan === itemId}
                                                            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border-light bg-bg-surface px-2.5 text-[10px] font-semibold text-text-muted hover:text-primary disabled:opacity-50"
                                                        >
                                                            <FileJson size={12} />
                                                            {plan ? 'Plan loaded' : details?.loadingPlan === itemId ? 'Loading...' : 'View plan'}
                                                        </button>
                                                    )}
                                                </div>
                                                {plan && (
                                                    <div className="mt-3 grid grid-cols-2 gap-2 text-[10px] sm:grid-cols-4">
                                                        <PlanMetric label="Actions" value={numberValue(planSummary.actions)} />
                                                        <PlanMetric label="Risks" value={numberValue(planSummary.risks)} warn />
                                                        <PlanMetric label="Conflicts" value={numberValue(planSummary.conflicts)} danger />
                                                        <PlanMetric label="Target" value={stringValue(plan.target_root) || 'metadata only'} wide />
                                                    </div>
                                                )}
                                                {stringValue(verification.status) && (
                                                    <div className="mt-3 grid grid-cols-2 gap-2 text-[10px] sm:grid-cols-4">
                                                        <PlanMetric label="Verification" value={stringValue(verification.status)} danger={stringValue(verification.status) === 'failed'} warn={stringValue(verification.status) === 'partial'} />
                                                        <PlanMetric label="Passed" value={`${numberValue(verification.passed)}/${numberValue(verification.checked)}`} />
                                                        <PlanMetric label="Warnings" value={numberValue(verification.warnings)} warn />
                                                        <PlanMetric label="Failures" value={numberValue(verification.failed)} danger />
                                                    </div>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </article>
    );
}

function DetailLine({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
    return (
        <div className="flex items-start justify-between gap-3 text-[10px]">
            <span className="capitalize text-text-muted">{label}</span>
            <span className={cn('max-w-[180px] truncate text-right font-semibold text-text-main', mono && 'font-mono')} title={value}>{value}</span>
        </div>
    );
}

function PlanMetric({ label, value, warn = false, danger = false, wide = false }: {
    label: string;
    value: number | string;
    warn?: boolean;
    danger?: boolean;
    wide?: boolean;
}) {
    return (
        <div className={cn('min-w-0 border-l border-border-light pl-2', wide && 'col-span-2 sm:col-span-1')}>
            <div className="uppercase text-text-muted">{label}</div>
            <div className={cn('mt-1 truncate font-semibold text-text-main', warn && Number(value) > 0 && 'text-amber-500', danger && Number(value) > 0 && 'text-red-500')} title={String(value)}>{value}</div>
        </div>
    );
}
