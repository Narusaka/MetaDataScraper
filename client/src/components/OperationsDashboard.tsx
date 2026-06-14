import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    AlertTriangle,
    ArrowRight,
    CheckCircle2,
    ClipboardCheck,
    Clock3,
    Gauge,
    History,
    KeyRound,
    Loader2,
    RefreshCw,
    ScanSearch,
    ShieldAlert,
    SlidersHorizontal,
} from 'lucide-react';
import { toast } from 'sonner';

import {
    dashboardAttentionCount,
    dashboardPrimaryAction,
    dashboardSuccessRate,
    recentTaskStatus,
} from '../lib/dashboardViewModel';
import { fetchDashboardSummary, openTaskEventSocket } from '../lib/taskApi';
import type { DashboardSummary, TaskSnapshot } from '../lib/types';
import { cn } from '../lib/utils';

export function OperationsDashboard({ active, onNavigate }: {
    active: boolean;
    onNavigate: (tab: string) => void;
}) {
    const [summary, setSummary] = useState<DashboardSummary>();
    const [loading, setLoading] = useState(false);
    const refreshTimer = useRef<number | undefined>(undefined);

    const loadSummary = useCallback(async (quiet = false) => {
        if (!quiet) setLoading(true);
        try {
            setSummary(await fetchDashboardSummary());
        } catch (error) {
            if (!quiet) toast.error(error instanceof Error ? error.message : 'Dashboard unavailable');
        } finally {
            if (!quiet) setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (!active) return;
        void loadSummary();
        const socket = openTaskEventSocket(() => {
            window.clearTimeout(refreshTimer.current);
            refreshTimer.current = window.setTimeout(() => void loadSummary(true), 150);
        });
        const interval = window.setInterval(() => void loadSummary(true), 15000);
        return () => {
            window.clearTimeout(refreshTimer.current);
            window.clearInterval(interval);
            socket.close();
        };
    }, [active, loadSummary]);

    const attention = useMemo(() => dashboardAttentionCount(summary), [summary]);
    const successRate = useMemo(() => dashboardSuccessRate(summary), [summary]);
    const primary = useMemo(() => dashboardPrimaryAction(summary), [summary]);

    if (!active) return null;

    return (
        <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-3xl border border-glass-border glass-panel-pro shadow-xl">
            <header className="shrink-0 border-b border-border-light px-5 py-5 md:px-7 md:py-6">
                <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                        <div className="flex items-center gap-2">
                            <Gauge size={18} className="text-primary" />
                            <h1 className="text-lg font-bold text-text-main">Media Operations</h1>
                            <span className={cn(
                                'rounded-md border px-2 py-0.5 text-[9px] font-bold uppercase',
                                summary?.worker.running
                                    ? 'border-blue-500/25 bg-blue-500/10 text-blue-500'
                                    : 'border-emerald-500/25 bg-emerald-500/10 text-emerald-500',
                            )}>
                                {summary?.worker.running ? 'Active' : 'Ready'}
                            </span>
                        </div>
                        <p className="mt-1 max-w-2xl text-xs text-text-muted">
                            One place to see what needs review, what is executing, and what can be recovered.
                        </p>
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            type="button"
                            onClick={() => void loadSummary()}
                            disabled={loading}
                            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border-light bg-bg-surface text-text-muted hover:text-primary disabled:opacity-50"
                            title="Refresh dashboard"
                        >
                            <RefreshCw size={15} className={cn(loading && 'animate-spin')} />
                        </button>
                        <button
                            type="button"
                            onClick={() => onNavigate(primary.tab)}
                            className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary px-4 text-[10px] font-bold uppercase text-white hover:brightness-110"
                        >
                            {primary.label}<ArrowRight size={13} />
                        </button>
                    </div>
                </div>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto">
                {!summary ? (
                    <div className="flex h-full min-h-[320px] items-center justify-center text-text-muted">
                        {loading ? <Loader2 size={24} className="animate-spin" /> : 'Dashboard data unavailable'}
                    </div>
                ) : (
                    <div className="space-y-0">
                        <div className="grid border-b border-border-light sm:grid-cols-2 xl:grid-cols-4">
                            <TopMetric
                                label="Needs attention"
                                value={attention}
                                detail={`${summary.queues.match_reviews} matches · ${summary.queues.plan_reviews.blocked + summary.queues.plan_reviews.drifted} plans`}
                                icon={AlertTriangle}
                                tone={attention ? 'warning' : 'success'}
                            />
                            <TopMetric
                                label="Running now"
                                value={summary.queues.executions.running}
                                detail={summary.worker.active_task_id ? `Task ${summary.worker.active_task_id.slice(0, 8)}` : 'No active execution'}
                                icon={Gauge}
                                tone={summary.queues.executions.running ? 'active' : 'neutral'}
                            />
                            <TopMetric
                                label="Rollback ready"
                                value={summary.queues.history.rollback_ready}
                                detail={`${summary.queues.history.finished} finished tasks`}
                                icon={History}
                                tone={summary.queues.history.rollback_ready ? 'warning' : 'neutral'}
                            />
                            <TopMetric
                                label="Success rate"
                                value={`${successRate}%`}
                                detail={`${summary.stats.total_success}/${summary.stats.total_media || 0} media items`}
                                icon={CheckCircle2}
                                tone={successRate >= 90 ? 'success' : 'warning'}
                            />
                        </div>

                        <div className="grid border-b border-border-light xl:grid-cols-[1.3fr_0.7fr]">
                            <div className="border-b border-border-light p-5 md:p-6 xl:border-b-0 xl:border-r">
                                <SectionTitle title="Workflow queues" subtitle="Open the next stage without hunting through task cards." />
                                <div className="mt-4 grid gap-2 sm:grid-cols-2">
                                    <QueueRow icon={ScanSearch} label="Library scan" value="Read-only inventory" onClick={() => onNavigate('library_scan')} />
                                    <QueueRow icon={ShieldAlert} label="Match review" value={`${summary.queues.match_reviews} pending`} attention={summary.queues.match_reviews > 0} onClick={() => onNavigate('match_review')} />
                                    <QueueRow icon={ClipboardCheck} label="Plan review" value={`${summary.queues.plan_reviews.ready} ready · ${summary.queues.plan_reviews.blocked} blocked`} attention={summary.queues.plan_reviews.blocked + summary.queues.plan_reviews.drifted > 0} onClick={() => onNavigate('plan_review')} />
                                    <QueueRow icon={Gauge} label="Execution" value={`${summary.queues.executions.running} running · ${summary.queues.executions.issues} issues`} attention={summary.queues.executions.issues > 0} onClick={() => onNavigate('execution')} />
                                    <QueueRow icon={History} label="History & rollback" value={`${summary.queues.history.rollback_ready} reversible`} attention={summary.queues.history.rollback_ready > 0} onClick={() => onNavigate('history')} />
                                    <QueueRow icon={SlidersHorizontal} label="Advanced planning" value="Organize, copy and scoped tasks" onClick={() => onNavigate('planning')} />
                                </div>
                            </div>

                            <div className="p-5 md:p-6">
                                <SectionTitle title="Service readiness" subtitle="Configuration presence, without exposing secrets." />
                                <div className="mt-4 divide-y divide-border-light">
                                    <ServiceRow name="TMDB" configured={summary.services.tmdb.configured} required />
                                    <ServiceRow name="Tavily" configured={summary.services.tavily.configured} />
                                    <ServiceRow name="Model translation" configured={summary.services.model.configured} />
                                </div>
                                <button
                                    type="button"
                                    onClick={() => onNavigate('settings')}
                                    className="mt-4 inline-flex h-9 items-center gap-2 text-[10px] font-bold uppercase text-primary hover:underline"
                                >
                                    <KeyRound size={13} /> Manage configuration
                                </button>
                            </div>
                        </div>

                        <div className="p-5 md:p-6">
                            <div className="flex flex-wrap items-end justify-between gap-3">
                                <SectionTitle title="Recent outcomes" subtitle="Latest completed work and recovery state." />
                                <button type="button" onClick={() => onNavigate('history')} className="text-[10px] font-bold uppercase text-primary hover:underline">
                                    View all history
                                </button>
                            </div>
                            <div className="mt-4 divide-y divide-border-light border-y border-border-light">
                                {summary.recent.length === 0 ? (
                                    <div className="py-8 text-center text-xs text-text-muted">No completed tasks yet.</div>
                                ) : summary.recent.map(task => <RecentTask key={task.id} task={task} />)}
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </section>
    );
}

function TopMetric({ label, value, detail, icon: Icon, tone }: {
    label: string;
    value: number | string;
    detail: string;
    icon: typeof Gauge;
    tone: 'neutral' | 'active' | 'success' | 'warning';
}) {
    return (
        <div className="min-h-[112px] border-b border-border-light p-5 last:border-b-0 sm:[&:nth-child(odd)]:border-r xl:border-b-0 xl:border-r xl:last:border-r-0">
            <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-text-muted">
                <Icon size={13} className={cn(
                    tone === 'active' && 'text-blue-500',
                    tone === 'success' && 'text-emerald-500',
                    tone === 'warning' && 'text-amber-500',
                )} />
                {label}
            </div>
            <div className="mt-2 font-mono text-2xl font-bold text-text-main">{value}</div>
            <div className="mt-1 truncate text-[10px] text-text-muted" title={detail}>{detail}</div>
        </div>
    );
}

function SectionTitle({ title, subtitle }: { title: string; subtitle: string }) {
    return (
        <div>
            <h2 className="text-sm font-bold text-text-main">{title}</h2>
            <p className="mt-1 text-[10px] text-text-muted">{subtitle}</p>
        </div>
    );
}

function QueueRow({ icon: Icon, label, value, attention = false, onClick }: {
    icon: typeof Gauge;
    label: string;
    value: string;
    attention?: boolean;
    onClick: () => void;
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            className="grid min-h-[64px] grid-cols-[32px_minmax(0,1fr)_16px] items-center gap-3 border-b border-border-light px-1 text-left hover:bg-black/[0.025] dark:hover:bg-white/[0.025]"
        >
            <span className={cn('flex h-8 w-8 items-center justify-center rounded-lg bg-bg-surface text-text-muted', attention && 'bg-amber-500/10 text-amber-500')}>
                <Icon size={15} />
            </span>
            <span className="min-w-0">
                <span className="block text-xs font-semibold text-text-main">{label}</span>
                <span className={cn('mt-1 block truncate text-[10px] text-text-muted', attention && 'text-amber-500')}>{value}</span>
            </span>
            <ArrowRight size={13} className="text-text-muted" />
        </button>
    );
}

function ServiceRow({ name, configured, required = false }: { name: string; configured: boolean; required?: boolean }) {
    return (
        <div className="flex min-h-[46px] items-center justify-between gap-3 text-xs">
            <span className="text-text-main">{name}{required && <span className="ml-1 text-red-500">*</span>}</span>
            <span className={cn(
                'inline-flex items-center gap-1.5 text-[10px] font-semibold',
                configured ? 'text-emerald-500' : required ? 'text-red-500' : 'text-text-muted',
            )}>
                <span className={cn('h-1.5 w-1.5 rounded-full', configured ? 'bg-emerald-500' : required ? 'bg-red-500' : 'bg-text-muted')} />
                {configured ? 'Configured' : 'Not configured'}
            </span>
        </div>
    );
}

function RecentTask({ task }: { task: TaskSnapshot }) {
    const summary = task.summary || {};
    const completed = typeof summary.completed === 'number' ? summary.completed : 0;
    const failed = typeof summary.failed === 'number' ? summary.failed : 0;
    const date = new Date(task.updated_at || task.created_at);
    const issue = ['failed', 'partial', 'stopped'].includes(task.status);
    return (
        <div className="grid min-h-[62px] grid-cols-[minmax(0,1fr)_auto] items-center gap-4 py-3 md:grid-cols-[minmax(0,1fr)_120px_120px]">
            <div className="min-w-0">
                <div className="truncate text-xs font-semibold text-text-main">{task.input_dir.split('/').pop() || task.input_dir}</div>
                <div className="mt-1 truncate font-mono text-[9px] text-text-muted">{task.input_dir}</div>
            </div>
            <div className="hidden text-[10px] text-text-muted md:block">
                <Clock3 size={11} className="mr-1 inline" />
                {Number.isNaN(date.getTime()) ? 'Unknown' : date.toLocaleDateString()}
            </div>
            <div className="text-right">
                <div className={cn('text-[10px] font-bold uppercase', issue ? 'text-amber-500' : 'text-emerald-500')}>
                    {recentTaskStatus(task)}
                </div>
                <div className="mt-1 font-mono text-[9px] text-text-muted">{completed} ok · {failed} failed</div>
            </div>
        </div>
    );
}
