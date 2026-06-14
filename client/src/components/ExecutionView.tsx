import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    AlertTriangle,
    Ban,
    CheckCircle2,
    ChevronDown,
    CircleDot,
    Clock3,
    Gauge,
    Loader2,
    RefreshCw,
    Search,
    Square,
} from 'lucide-react';
import { toast } from 'sonner';

import {
    deriveExecutions,
    executionCurrentItem,
    executionCurrentOperation,
    executionEventLabel,
    executionItemSummary,
    executionIsRunning,
    executionPhaseLabel,
    executionPhasePercent,
    executionStats,
    type ExecutionFilter,
} from '../lib/executionViewModel';
import { cancelTask, fetchExecutions, openTaskEventSocket } from '../lib/taskApi';
import type { ExecutionRecord, MetadataRecord } from '../lib/types';
import { cn } from '../lib/utils';

interface ExecutionViewProps {
    active: boolean;
}

const numberValue = (value: unknown) => typeof value === 'number' ? value : 0;
const stringValue = (value: unknown) => typeof value === 'string' ? value : '';

export function ExecutionView({ active }: ExecutionViewProps) {
    const [executions, setExecutions] = useState<ExecutionRecord[]>([]);
    const [filter, setFilter] = useState<ExecutionFilter>('all');
    const [query, setQuery] = useState('');
    const [loading, setLoading] = useState(false);
    const [cancelling, setCancelling] = useState<string>();
    const [expanded, setExpanded] = useState<Record<string, boolean>>({});
    const refreshTimer = useRef<number | undefined>(undefined);

    const loadExecutions = useCallback(async (quiet = false) => {
        if (!quiet) setLoading(true);
        try {
            const response = await fetchExecutions();
            setExecutions(response.executions || []);
        } catch (error) {
            if (!quiet) toast.error(error instanceof Error ? error.message : 'Execution queue unavailable');
        } finally {
            if (!quiet) setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (!active) return;
        void loadExecutions();
        const socket = openTaskEventSocket(() => {
            window.clearTimeout(refreshTimer.current);
            refreshTimer.current = window.setTimeout(() => void loadExecutions(true), 120);
        });
        return () => {
            window.clearTimeout(refreshTimer.current);
            socket.close();
        };
    }, [active, loadExecutions]);

    const stats = useMemo(() => executionStats(executions), [executions]);
    const visible = useMemo(() => deriveExecutions(executions, filter, query), [executions, filter, query]);

    const handleCancel = async (execution: ExecutionRecord) => {
        if (!window.confirm(`Cancel execution ${execution.id.slice(0, 8)}?\nThe current atomic operation will finish before cancellation takes effect.`)) return;
        setCancelling(execution.id);
        try {
            await cancelTask(execution.id);
            setExecutions(current => current.map(item => item.id === execution.id
                ? { ...item, status: 'cancel_requested', phase: 'cancelling' }
                : item));
            toast.success('Cancellation requested');
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Cancellation failed');
        } finally {
            setCancelling(undefined);
        }
    };

    return (
        <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-3xl border border-glass-border glass-panel-pro shadow-xl">
            <header className="shrink-0 border-b border-border-light px-5 py-5 md:px-6">
                <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                        <div className="flex items-center gap-2">
                            <Gauge size={18} className="text-primary" />
                            <h2 className="text-lg font-bold text-text-main">Execution</h2>
                        </div>
                        <p className="mt-1 text-xs text-text-muted">Live progress for confirmed, locked plans.</p>
                    </div>
                    <button
                        type="button"
                        onClick={() => void loadExecutions()}
                        disabled={loading}
                        className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border-light bg-bg-surface text-text-muted hover:text-primary disabled:opacity-50"
                        title="Refresh executions"
                    >
                        <RefreshCw size={15} className={cn(loading && 'animate-spin')} />
                    </button>
                </div>

                <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-5">
                    <Metric label="Executions" value={stats.total} icon={Gauge} />
                    <Metric label="Running" value={stats.running} icon={Loader2} tone={stats.running ? 'active' : 'neutral'} />
                    <Metric label="Completed" value={stats.completed} icon={CheckCircle2} tone="success" />
                    <Metric label="Issues" value={stats.issues} icon={AlertTriangle} tone={stats.issues ? 'danger' : 'neutral'} />
                    <Metric label="Items processed" value={stats.processed} icon={CircleDot} />
                </div>

                <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                    <div className="flex max-w-full overflow-x-auto rounded-lg border border-border-light bg-bg-surface p-1">
                        {([
                            ['all', `All ${stats.total}`],
                            ['running', `Running ${stats.running}`],
                            ['issues', `Issues ${stats.issues}`],
                            ['done', 'Finished'],
                        ] as Array<[ExecutionFilter, string]>).map(([value, label]) => (
                            <button
                                key={value}
                                type="button"
                                onClick={() => setFilter(value)}
                                className={cn(
                                    'h-8 shrink-0 rounded-md px-3 text-[11px] font-semibold transition-colors',
                                    filter === value ? 'bg-primary text-white' : 'text-text-muted hover:text-text-main',
                                )}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                    <label className="flex h-10 min-w-0 flex-1 items-center gap-2 rounded-lg border border-border-light bg-bg-surface px-3 sm:min-w-[240px] lg:max-w-sm">
                        <Search size={14} className="shrink-0 text-text-muted" />
                        <input
                            value={query}
                            onChange={event => setQuery(event.target.value)}
                            placeholder="Search path, execution ID..."
                            className="min-w-0 flex-1 bg-transparent text-xs outline-none placeholder:text-text-muted/60"
                        />
                    </label>
                </div>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto">
                {visible.length === 0 ? (
                    <div className="flex h-full min-h-[280px] flex-col items-center justify-center gap-3 text-text-muted">
                        <Gauge size={30} className="opacity-35" />
                        <p className="text-sm font-semibold">{loading ? 'Loading executions...' : 'No matching executions'}</p>
                        <p className="max-w-sm text-center text-xs">Confirmed plans appear here as soon as execution starts.</p>
                    </div>
                ) : (
                    <div className="divide-y divide-border-light">
                        {visible.map(execution => (
                            <ExecutionRow
                                key={execution.id}
                                execution={execution}
                                expanded={!!expanded[execution.id]}
                                cancelling={cancelling === execution.id}
                                onToggle={() => setExpanded(current => ({ ...current, [execution.id]: !current[execution.id] }))}
                                onCancel={() => void handleCancel(execution)}
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
    icon: typeof Gauge;
    tone?: 'neutral' | 'active' | 'success' | 'danger';
}) {
    return (
        <div className="min-h-[72px] border-l-2 border-border-light px-3 py-2">
            <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-text-muted">
                <Icon size={13} className={cn(
                    tone === 'active' && 'text-blue-500',
                    tone === 'success' && 'text-emerald-500',
                    tone === 'danger' && 'text-red-500',
                )} />
                {label}
            </div>
            <div className="mt-2 font-mono text-xl font-bold text-text-main">{value}</div>
        </div>
    );
}

function ExecutionRow({ execution, expanded, cancelling, onToggle, onCancel }: {
    execution: ExecutionRecord;
    expanded: boolean;
    cancelling: boolean;
    onToggle: () => void;
    onCancel: () => void;
}) {
    const progress = execution.progress || {};
    const total = numberValue(progress.total);
    const processed = numberValue(progress.processed);
    const percent = executionPhasePercent(execution);
    const currentItem = executionCurrentItem(execution);
    const currentOperation = executionCurrentOperation(execution);
    const running = executionIsRunning(execution);
    const issue = ['failed', 'partial', 'stopped', 'cancelled', 'interrupted'].includes(execution.status);
    const sourcePlan = stringValue(execution.config?.source_plan_task_id);
    const timeline = (execution.timeline || []).slice().reverse().slice(0, 12);
    const itemEntries = Object.entries(execution.items || {});
    const date = new Date(execution.updated_at || execution.created_at);

    return (
        <article>
            <div className="px-5 py-5 md:px-6">
                <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(220px,0.8fr)_auto] lg:items-center">
                    <button type="button" onClick={onToggle} className="min-w-0 text-left">
                        <div className="flex items-start gap-3">
                            <span className={cn(
                                'mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg',
                                running ? 'bg-blue-500/10 text-blue-500' : issue ? 'bg-red-500/10 text-red-500' : 'bg-emerald-500/10 text-emerald-500',
                            )}>
                                {running ? <Loader2 size={16} className="animate-spin" /> : issue ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
                            </span>
                            <span className="min-w-0 flex-1">
                                <span className="flex flex-wrap items-center gap-2">
                                    <span className="truncate text-sm font-semibold text-text-main">{execution.input_dir.split('/').pop() || execution.input_dir}</span>
                                    <StatusBadge status={execution.status} />
                                </span>
                                <span className="mt-1 block truncate font-mono text-[10px] text-text-muted">{execution.input_dir}</span>
                                <span className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-text-muted">
                                    <span>Execution {execution.id.slice(0, 8)}</span>
                                    {sourcePlan && <span>Plan {sourcePlan.slice(0, 8)}</span>}
                                    <span>{Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString()}</span>
                                </span>
                            </span>
                        </div>
                    </button>

                    <div className="min-w-0">
                        <div className="mb-2 flex items-center justify-between gap-3 text-[11px]">
                            <span className="font-semibold text-text-main">{executionPhaseLabel(execution.phase)}</span>
                            <span className="font-mono text-text-muted">{total ? `${processed}/${total}` : `${percent}%`}</span>
                        </div>
                        <div className="h-1.5 overflow-hidden rounded-full bg-bg-surface">
                            <div
                                className={cn('h-full rounded-full transition-[width] duration-500', issue ? 'bg-red-500' : execution.status === 'completed' ? 'bg-emerald-500' : 'bg-blue-500')}
                                style={{ width: `${percent}%` }}
                            />
                        </div>
                        {currentItem && (
                            <div className="mt-2 truncate text-[10px] text-text-muted">
                                {stringValue(currentItem.name) || stringValue(currentItem.path) || currentItem.id}
                            </div>
                        )}
                        {currentOperation && (
                            <div
                                className="mt-1 flex min-w-0 items-center gap-1.5 text-[10px] text-blue-500"
                                title={[
                                    stringValue(currentOperation.source),
                                    stringValue(currentOperation.destination),
                                ].filter(Boolean).join(' → ')}
                            >
                                <CircleDot size={10} className="shrink-0 animate-pulse" />
                                <span className="shrink-0 font-semibold">
                                    {stringValue(currentOperation.action).replaceAll('_', ' ')}
                                </span>
                                <span className="truncate font-mono">
                                    {operationPathLabel(currentOperation)}
                                </span>
                            </div>
                        )}
                    </div>

                    <div className="flex items-center justify-end gap-2">
                        {running && execution.status !== 'cancel_requested' && (
                            <button
                                type="button"
                                onClick={event => { event.stopPropagation(); onCancel(); }}
                                disabled={cancelling}
                                className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-red-500/30 bg-red-500/10 px-2.5 text-[10px] font-bold text-red-500 hover:bg-red-500/20 disabled:opacity-50"
                            >
                                {cancelling ? <Loader2 size={13} className="animate-spin" /> : <Square size={12} fill="currentColor" />}
                                Cancel
                            </button>
                        )}
                        {execution.status === 'cancel_requested' && (
                            <span className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 text-[10px] font-bold text-amber-500">
                                <Ban size={13} /> Cancelling
                            </span>
                        )}
                        <button
                            type="button"
                            onClick={onToggle}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border-light bg-bg-surface text-text-muted"
                            title={expanded ? 'Collapse execution details' : 'Open execution details'}
                        >
                            <ChevronDown size={15} className={cn('transition-transform', expanded && 'rotate-180')} />
                        </button>
                    </div>
                </div>
            </div>

            {expanded && (
                <div className="border-t border-border-light bg-black/[0.025] px-5 py-5 dark:bg-white/[0.02] md:px-6">
                    <div className="grid gap-6 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
                        <div>
                            <h3 className="text-[10px] font-bold uppercase tracking-[0.18em] text-text-muted">Items</h3>
                            <div className="mt-3 space-y-2">
                                {itemEntries.length === 0 ? (
                                    <p className="text-xs text-text-muted">Waiting for scanner output.</p>
                                ) : itemEntries.map(([itemId, raw]) => {
                                    const item = raw as MetadataRecord;
                                    const status = stringValue(item.status) || 'created';
                                    const summary = executionItemSummary(item);
                                    const hasIssue = !!stringValue(item.error) || ['failed', 'partial'].includes(status);
                                    const operationSummary = item.operation_summary && typeof item.operation_summary === 'object'
                                        ? item.operation_summary as MetadataRecord
                                        : {};
                                    return (
                                        <div key={itemId} className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 border-b border-border-light pb-2 text-xs last:border-0">
                                            <div className="min-w-0">
                                                <div className="truncate font-semibold text-text-main">{stringValue(item.name) || itemId.split('/').pop()}</div>
                                                <div className={cn('mt-1 truncate text-[10px]', hasIssue ? 'text-red-500' : 'text-text-muted')}>
                                                    {summary || itemId}
                                                </div>
                                                {(numberValue(operationSummary.completed) > 0 || numberValue(operationSummary.failed) > 0) && (
                                                    <div className="mt-1 flex gap-3 font-mono text-[9px] text-text-muted">
                                                        <span>{numberValue(operationSummary.completed)} operations completed</span>
                                                        {numberValue(operationSummary.failed) > 0 && (
                                                            <span className="text-red-500">{numberValue(operationSummary.failed)} failed</span>
                                                        )}
                                                    </div>
                                                )}
                                            </div>
                                            <span className="self-start font-mono text-[10px] uppercase text-text-muted">{status}</span>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>

                        <div>
                            <h3 className="text-[10px] font-bold uppercase tracking-[0.18em] text-text-muted">Structured timeline</h3>
                            <div className="mt-3 space-y-2">
                                {timeline.length === 0 ? (
                                    <p className="text-xs text-text-muted">No execution events recorded yet.</p>
                                ) : timeline.map((event, index) => {
                                    const eventDate = new Date(event.timestamp);
                                    return (
                                        <div key={event.id || `${event.type}-${index}`} className="grid grid-cols-[16px_minmax(0,1fr)_auto] items-start gap-2 text-xs">
                                            <Clock3 size={12} className="mt-0.5 text-text-muted" />
                                            <div className="min-w-0">
                                                <div className="break-words text-text-main">{executionEventLabel(event)}</div>
                                                <div className="mt-0.5 truncate font-mono text-[9px] text-text-muted">{event.type}</div>
                                            </div>
                                            <time className="font-mono text-[9px] text-text-muted">
                                                {Number.isNaN(eventDate.getTime()) ? '' : eventDate.toLocaleTimeString()}
                                            </time>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </article>
    );
}

function operationPathLabel(operation: MetadataRecord) {
    const source = stringValue(operation.source);
    const destination = stringValue(operation.destination);
    const sourceName = source.split('/').pop() || source;
    const destinationName = destination.split('/').pop() || destination;
    if (sourceName && destinationName) return `${sourceName} → ${destinationName}`;
    return destinationName || sourceName;
}

function StatusBadge({ status }: { status: string }) {
    const issue = ['failed', 'partial', 'stopped', 'cancelled', 'interrupted'].includes(status);
    const running = ['created', 'running', 'cancel_requested'].includes(status);
    return (
        <span className={cn(
            'inline-flex h-6 items-center rounded-md border px-2 text-[9px] font-bold uppercase',
            running && 'border-blue-500/25 bg-blue-500/10 text-blue-500',
            issue && 'border-red-500/25 bg-red-500/10 text-red-500',
            !running && !issue && 'border-emerald-500/25 bg-emerald-500/10 text-emerald-500',
        )}>
            {status.replaceAll('_', ' ')}
        </span>
    );
}
