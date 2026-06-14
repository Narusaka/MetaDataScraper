import { useCallback, useEffect, useMemo, useState } from 'react';
import {
    AlertTriangle,
    ArrowRight,
    CheckCircle2,
    ChevronDown,
    Clock3,
    FileCheck2,
    FileJson,
    FileWarning,
    FolderOutput,
    Loader2,
    Play,
    RefreshCw,
    Search,
    ShieldCheck,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { toast } from 'sonner';

import {
    executeConfirmedPlan,
    fetchPlanArtifact,
    fetchPlanReviews,
    planTask,
} from '../lib/taskApi';
import {
    buildPlanReviewReplanPayload,
    derivePlanReviews,
    planDiagnostics,
    planReviewStats,
    planReviewTitle,
    type PlanReviewFilter,
} from '../lib/planReviewViewModel';
import type {
    ExecutionPlan,
    MetadataRecord,
    PlanArtifactResponse,
    PlanReviewRecord,
} from '../lib/types';
import { cn } from '../lib/utils';
import { useSystemStatus } from '../lib/systemStatusContext';

const recordValue = (value: unknown): MetadataRecord => (
    value && typeof value === 'object' && !Array.isArray(value) ? value as MetadataRecord : {}
);
const recordsValue = (value: unknown): MetadataRecord[] => (
    Array.isArray(value) ? value.filter(entry => entry && typeof entry === 'object') as MetadataRecord[] : []
);
const numberValue = (value: unknown) => typeof value === 'number' ? value : 0;
const stringValue = (value: unknown) => typeof value === 'string' ? value : '';

export function PlanReviewView({ active }: { active: boolean }) {
    const [plans, setPlans] = useState<PlanReviewRecord[]>([]);
    const [filter, setFilter] = useState<PlanReviewFilter>('all');
    const [query, setQuery] = useState('');
    const [loading, setLoading] = useState(false);
    const [expanded, setExpanded] = useState<Record<string, boolean>>({});
    const [artifacts, setArtifacts] = useState<Record<string, PlanArtifactResponse>>({});
    const [artifactErrors, setArtifactErrors] = useState<Record<string, string>>({});
    const [artifactLoading, setArtifactLoading] = useState<string>();
    const [executing, setExecuting] = useState<string>();
    const [replanning, setReplanning] = useState<string>();
    const { running, refresh } = useSystemStatus();

    const loadPlans = useCallback(async () => {
        setLoading(true);
        try {
            const response = await fetchPlanReviews();
            setPlans(response.plans || []);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Plan review queue unavailable');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (active) void loadPlans();
    }, [active, loadPlans]);

    const stats = useMemo(() => planReviewStats(plans), [plans]);
    const visiblePlans = useMemo(
        () => derivePlanReviews(plans, filter, query),
        [filter, plans, query],
    );

    const keyFor = (record: PlanReviewRecord) => `${record.task_id}:${record.item_id}`;

    const togglePlan = async (record: PlanReviewRecord) => {
        const key = keyFor(record);
        const opening = !expanded[key];
        setExpanded(current => ({ ...current, [key]: opening }));
        if (!opening || artifacts[key] || artifactLoading === key) return;
        setArtifactLoading(key);
        setArtifactErrors(current => {
            const next = { ...current };
            delete next[key];
            return next;
        });
        try {
            const artifact = await fetchPlanArtifact(record.task_id, record.item_id);
            setArtifacts(current => ({ ...current, [key]: artifact }));
        } catch (error) {
            const message = error instanceof Error ? error.message : 'Full plan unavailable';
            setArtifactErrors(current => ({ ...current, [key]: message }));
            toast.error(message);
        } finally {
            setArtifactLoading(undefined);
        }
    };

    const handleExecute = async (record: PlanReviewRecord) => {
        if (running) {
            toast.error('Another task is already running');
            return;
        }
        if (record.review_status !== 'ready') {
            toast.error(record.review_status === 'drifted' ? 'Replan after filesystem drift' : 'Resolve plan blockers first');
            return;
        }
        const item = recordValue(record.item);
        const digest = stringValue(item.plan_digest);
        if (!digest) {
            toast.error('Locked plan digest is missing');
            return;
        }
        const plan = artifacts[keyFor(record)]?.plan || recordValue(item.plan) as ExecutionPlan;
        const summary = plan.summary || {};
        if (!window.confirm([
            `Execute the locked plan for ${planReviewTitle(record)}?`,
            `${summary.actions || 0} actions, ${summary.metadata_writes || 0} metadata writes, ${summary.risks || 0} risks.`,
            `Digest ${digest.slice(0, 12)} will be verified again before any write.`,
        ].join('\n'))) return;

        const key = keyFor(record);
        setExecuting(key);
        try {
            const response = await executeConfirmedPlan(record.task_id, record.item_id, digest);
            setPlans(current => current.filter(entry => keyFor(entry) !== key));
            await refresh();
            toast.success(`Execution started as ${response.task_id.slice(0, 8)}`);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Confirmed execution failed');
            await loadPlans();
        } finally {
            setExecuting(undefined);
        }
    };

    const handleReplan = async (record: PlanReviewRecord) => {
        if (running) {
            toast.error('Another task is already running');
            return;
        }
        const key = keyFor(record);
        setReplanning(key);
        try {
            await planTask(buildPlanReviewReplanPayload(record));
            await refresh();
            toast.success('New locked audit plan queued');
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Unable to regenerate plan');
        } finally {
            setReplanning(undefined);
        }
    };

    if (!active) return null;

    return (
        <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-glass-border glass-panel-pro shadow-xl">
            <header className="shrink-0 border-b border-border-light px-4 py-4 md:px-6">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                        <div className="flex items-center gap-2">
                            <FileCheck2 size={18} className="text-primary" />
                            <h2 className="text-lg font-bold text-text-main">Plan Review</h2>
                        </div>
                        <p className="mt-1 text-xs text-text-muted">
                            Inspect locked file changes, blockers and risk evidence before execution.
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={() => void loadPlans()}
                        disabled={loading}
                        className="flex h-9 w-9 items-center justify-center rounded-md border border-border-light text-text-muted hover:text-primary disabled:opacity-40"
                        title="Refresh plan review queue"
                    >
                        <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                    </button>
                </div>

                <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                    <ReviewMetric label="Pending" value={stats.total} icon={Clock3} />
                    <ReviewMetric label="Ready" value={stats.ready} icon={CheckCircle2} tone="ok" />
                    <ReviewMetric label="Blocked" value={stats.blocked} icon={AlertTriangle} tone="danger" />
                    <ReviewMetric label="Drifted" value={stats.drifted} icon={FileWarning} tone="warn" />
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-2">
                    <div className="flex h-9 min-w-[220px] flex-1 items-center gap-2 rounded-lg border border-border-light bg-bg-surface px-3">
                        <Search size={13} className="shrink-0 text-text-muted" />
                        <input
                            value={query}
                            onChange={event => setQuery(event.target.value)}
                            placeholder="Search title, path, TMDB ID..."
                            className="min-w-0 flex-1 bg-transparent text-xs outline-none placeholder:text-text-muted/60"
                        />
                    </div>
                    <div className="flex rounded-lg border border-border-light bg-bg-surface p-1">
                        {([
                            ['all', `All ${stats.total}`],
                            ['ready', `Ready ${stats.ready}`],
                            ['blocked', `Blocked ${stats.blocked}`],
                            ['drifted', `Drifted ${stats.drifted}`],
                        ] as Array<[PlanReviewFilter, string]>).map(([value, label]) => (
                            <button
                                key={value}
                                type="button"
                                onClick={() => setFilter(value)}
                                className={cn(
                                    'h-7 rounded-md px-2 text-[9px] font-bold uppercase',
                                    filter === value ? 'bg-primary text-white' : 'text-text-muted hover:text-text-main',
                                )}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                </div>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto p-3 md:p-4">
                {loading && plans.length === 0 ? (
                    <div className="flex h-full items-center justify-center gap-2 text-xs text-text-muted">
                        <Loader2 size={14} className="animate-spin" />
                        Loading locked plans
                    </div>
                ) : visiblePlans.length === 0 ? (
                    <div className="flex h-full min-h-[260px] flex-col items-center justify-center gap-3 px-6 text-center">
                        <span className="flex h-14 w-14 items-center justify-center rounded-lg border border-emerald-500/20 bg-emerald-500/10 text-emerald-500">
                            <ShieldCheck size={24} />
                        </span>
                        <div className="text-sm font-semibold text-text-main">No plans need review</div>
                        <p className="max-w-md text-xs leading-relaxed text-text-muted">
                            Generate an audit plan from Library Scan or Dashboard. Locked plans will appear here before execution.
                        </p>
                    </div>
                ) : (
                    <div className="space-y-3">
                        {visiblePlans.map(record => {
                            const key = keyFor(record);
                            return (
                                <PlanReviewRow
                                    key={key}
                                    record={record}
                                    artifact={artifacts[key]}
                                    artifactError={artifactErrors[key]}
                                    expanded={!!expanded[key]}
                                    loading={artifactLoading === key}
                                    executing={executing === key}
                                    replanning={replanning === key}
                                    disabled={running || !!executing || !!replanning}
                                    onToggle={() => void togglePlan(record)}
                                    onExecute={() => void handleExecute(record)}
                                    onReplan={() => void handleReplan(record)}
                                />
                            );
                        })}
                    </div>
                )}
            </div>
        </section>
    );
}

function PlanReviewRow({
    record,
    artifact,
    artifactError,
    expanded,
    loading,
    executing,
    replanning,
    disabled,
    onToggle,
    onExecute,
    onReplan,
}: {
    record: PlanReviewRecord;
    artifact?: PlanArtifactResponse;
    artifactError?: string;
    expanded: boolean;
    loading: boolean;
    executing: boolean;
    replanning: boolean;
    disabled: boolean;
    onToggle: () => void;
    onExecute: () => void;
    onReplan: () => void;
}) {
    const item = recordValue(record.item);
    const compactPlan = recordValue(item.plan);
    const plan = artifact?.plan || compactPlan as ExecutionPlan;
    const summary = plan.summary || recordValue(item.plan_summary);
    const digest = stringValue(item.plan_digest);
    const source = stringValue(plan.source_path) || stringValue(item.path) || record.item_id;
    const target = stringValue(plan.target_root) || stringValue(item.output_path);
    const diagnostics = planDiagnostics(plan);
    const primaryDiagnostic = diagnostics[0];
    const preflight = recordValue(plan.preflight);
    const preflightChecks = recordsValue(preflight.checks);
    const blockedPreflight = preflightChecks.find(check => stringValue(check.status) === 'blocked');
    const taskConfig = recordValue(record.task_config);
    const settingsRevision = numberValue(taskConfig.settings_revision);
    const settingsFingerprint = stringValue(taskConfig.settings_fingerprint);
    const statusTone = record.review_status === 'ready'
        ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-500'
        : record.review_status === 'drifted'
            ? 'border-amber-500/25 bg-amber-500/10 text-amber-500'
            : 'border-red-500/25 bg-red-500/10 text-red-500';

    return (
        <article className="overflow-hidden rounded-lg border border-border-light bg-bg-panel">
            <div className="p-3 md:p-4">
                <div className="flex flex-wrap items-start gap-3">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                        <FileJson size={18} />
                    </span>
                    <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                            <h3 className="min-w-0 truncate text-sm font-bold text-text-main">{planReviewTitle(record)}</h3>
                            <span className={cn('rounded-md border px-1.5 py-0.5 text-[8px] font-bold uppercase', statusTone)}>
                                {record.review_status}
                            </span>
                            {digest && <span className="font-mono text-[9px] text-text-muted">{digest.slice(0, 12)}</span>}
                            {artifact?.integrity_status === 'verified' && (
                                <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/25 bg-emerald-500/10 px-1.5 py-0.5 text-[8px] font-bold uppercase text-emerald-500">
                                    <ShieldCheck size={9} />
                                    Envelope verified
                                </span>
                            )}
                            {settingsFingerprint && (
                                <span
                                    className="font-mono text-[9px] text-text-muted"
                                    title={`Settings fingerprint ${settingsFingerprint}`}
                                >
                                    cfg r{settingsRevision} · {settingsFingerprint.slice(0, 8)}
                                </span>
                            )}
                        </div>
                        <div className="mt-1 flex min-w-0 items-center gap-1 font-mono text-[9px] text-text-muted">
                            <span className="truncate" title={source}>{source}</span>
                            {target && (
                                <>
                                    <ArrowRight size={10} className="shrink-0" />
                                    <span className="truncate" title={target}>{target}</span>
                                </>
                            )}
                        </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                        <button
                            type="button"
                            onClick={onReplan}
                            disabled={disabled}
                            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border-light px-2.5 text-[9px] font-bold uppercase text-text-muted hover:text-primary disabled:opacity-35"
                        >
                            {replanning ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
                            Replan
                        </button>
                        <button
                            type="button"
                            onClick={onExecute}
                            disabled={disabled || record.review_status !== 'ready'}
                            className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-[9px] font-bold uppercase text-white hover:brightness-110 disabled:opacity-35"
                        >
                            {executing ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
                            Execute
                        </button>
                    </div>
                </div>

                {primaryDiagnostic && (
                    <div className={cn(
                        'mt-3 flex items-start gap-2 rounded-md border px-2.5 py-2',
                        primaryDiagnostic.level === 'error'
                            ? 'border-red-500/20 bg-red-500/[0.05]'
                            : 'border-amber-500/20 bg-amber-500/[0.05]',
                    )}>
                        <FileWarning
                            size={13}
                            className={cn(
                                'mt-0.5 shrink-0',
                                primaryDiagnostic.level === 'error' ? 'text-red-500' : 'text-amber-500',
                            )}
                        />
                        <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-1.5">
                                <span className={cn(
                                    'text-[9px] font-bold uppercase',
                                    primaryDiagnostic.level === 'error' ? 'text-red-500' : 'text-amber-500',
                                )}>
                                    {primaryDiagnostic.code.replaceAll('_', ' ')}
                                </span>
                                {primaryDiagnostic.context && (
                                    <span className="rounded bg-black/[0.04] px-1.5 py-0.5 font-mono text-[8px] text-text-muted dark:bg-white/[0.05]">
                                        {primaryDiagnostic.context}
                                    </span>
                                )}
                            </div>
                            <p className="mt-0.5 text-[10px] leading-relaxed text-text-main">{primaryDiagnostic.message}</p>
                        </div>
                        {diagnostics.length > 1 && (
                            <span className="shrink-0 text-[8px] font-bold text-text-muted">+{diagnostics.length - 1}</span>
                        )}
                    </div>
                )}

                {record.settings_drift && (
                    <div className="mt-3 flex items-start gap-2 rounded-md border border-amber-500/20 bg-amber-500/[0.05] px-2.5 py-2">
                        <RefreshCw size={13} className="mt-0.5 shrink-0 text-amber-500" />
                        <div className="min-w-0">
                            <div className="text-[9px] font-bold uppercase text-amber-500">
                                Settings changed after audit
                            </div>
                            <p className="mt-0.5 text-[10px] leading-relaxed text-text-main">
                                This plan used revision {record.settings_drift.expected_revision ?? 'unknown'};
                                current revision is {record.settings_drift.current_revision ?? 'unknown'}. Generate a new locked plan.
                            </p>
                        </div>
                    </div>
                )}

                {record.artifact_integrity && record.artifact_integrity.status !== 'verified' && (
                    <div className="mt-3 flex items-start gap-2 rounded-md border border-red-500/20 bg-red-500/[0.05] px-2.5 py-2">
                        <FileWarning size={13} className="mt-0.5 shrink-0 text-red-500" />
                        <div className="min-w-0">
                            <div className="text-[9px] font-bold uppercase text-red-500">
                                {record.artifact_integrity.code?.replaceAll('_', ' ') || 'Plan artifact invalid'}
                            </div>
                            <p className="mt-0.5 text-[10px] leading-relaxed text-text-main">
                                {record.artifact_integrity.message || 'The locked plan evidence cannot be verified.'}
                            </p>
                            <p className="mt-1 text-[9px] text-text-muted">Generate a new audit before execution.</p>
                        </div>
                    </div>
                )}

                {blockedPreflight && (
                    <div className="mt-3 flex items-start gap-2 rounded-md border border-red-500/20 bg-red-500/[0.05] px-2.5 py-2">
                        <AlertTriangle size={13} className="mt-0.5 shrink-0 text-red-500" />
                        <div className="min-w-0">
                            <div className="text-[9px] font-bold uppercase text-red-500">
                                Execution preflight blocked
                            </div>
                            <p className="mt-0.5 text-[10px] leading-relaxed text-text-main">
                                {stringValue(blockedPreflight.message)}
                            </p>
                        </div>
                    </div>
                )}

                <div className="mt-3 grid grid-cols-3 gap-1.5 sm:grid-cols-6">
                    <PlanMetric label="Actions" value={numberValue(summary.actions)} />
                    <PlanMetric label="Ready" value={numberValue(summary.ready)} tone="ok" />
                    <PlanMetric label="Blocked" value={numberValue(summary.blocked) + numberValue(summary.conflicts)} tone="danger" />
                    <PlanMetric label="Risks" value={numberValue(summary.risks)} tone="warn" />
                    <PlanMetric label="Metadata" value={numberValue(summary.metadata_writes)} />
                    <PlanMetric label="Missing" value={numberValue(summary.missing_episodes)} tone="warn" />
                </div>

                <button
                    type="button"
                    onClick={onToggle}
                    className="mt-3 flex h-8 w-full items-center justify-between border-t border-border-light pt-3 text-[9px] font-bold uppercase text-text-muted hover:text-text-main"
                >
                    <span>{expanded ? 'Hide full plan' : 'Inspect full plan'}</span>
                    {loading ? <Loader2 size={12} className="animate-spin" /> : <ChevronDown size={12} className={expanded ? 'rotate-180' : ''} />}
                </button>
            </div>

            {expanded && (
                <PlanEvidence
                    plan={artifact?.plan}
                    preflight={preflight}
                    loading={loading}
                    error={artifactError}
                />
            )}
        </article>
    );
}

function PlanEvidence({ plan, preflight, loading, error }: {
    plan?: ExecutionPlan;
    preflight: MetadataRecord;
    loading: boolean;
    error?: string;
}) {
    if (loading && !plan) {
        return <div className="border-t border-border-light px-4 py-5 text-xs text-text-muted">Loading immutable plan artifact...</div>;
    }
    if (!plan) {
        return (
            <div className="border-t border-border-light px-4 py-5">
                <div className="flex items-start gap-2 rounded-md border border-red-500/20 bg-red-500/[0.05] px-3 py-2.5">
                    <FileWarning size={14} className="mt-0.5 shrink-0 text-red-500" />
                    <div>
                        <div className="text-[9px] font-bold uppercase text-red-500">Plan evidence unavailable</div>
                        <p className="mt-1 text-[10px] leading-relaxed text-text-main">
                            {error || 'The immutable plan artifact could not be loaded.'}
                        </p>
                        <p className="mt-1 text-[9px] text-text-muted">
                            Regenerate the audit before execution when integrity verification fails.
                        </p>
                    </div>
                </div>
            </div>
        );
    }
    const conflicts = recordsValue(plan.conflicts);
    const diagnostics = planDiagnostics(plan);
    const diagnosticCodeSet = new Set(diagnostics.map(diagnostic => diagnostic.code));
    const risks = recordsValue(plan.risks).filter(risk => !diagnosticCodeSet.has(stringValue(risk.code)));
    const actions = recordsValue(plan.actions);
    const preflightChecks = recordsValue(preflight.checks);
    const preflightStatus = stringValue(preflight.status);

    return (
        <div className="border-t border-border-light bg-bg-surface/40 p-3 md:p-4">
            {preflightChecks.length > 0 && (
                <div className="mb-4">
                    <div className={cn(
                        'mb-1.5 flex items-center gap-1.5 text-[9px] font-bold uppercase',
                        preflightStatus === 'blocked' ? 'text-red-500' : preflightStatus === 'warning' ? 'text-amber-500' : 'text-emerald-500',
                    )}>
                        <ShieldCheck size={11} />
                        Execution preflight {preflightStatus || 'unknown'}
                    </div>
                    <div className="grid gap-1.5 lg:grid-cols-3">
                        {preflightChecks.map((check, index) => {
                            const status = stringValue(check.status);
                            return (
                                <div
                                    key={`${stringValue(check.code)}:${index}`}
                                    className={cn(
                                        'rounded-md border px-2.5 py-2',
                                        status === 'blocked'
                                            ? 'border-red-500/20 bg-red-500/[0.05]'
                                            : status === 'warning'
                                                ? 'border-amber-500/20 bg-amber-500/[0.05]'
                                                : 'border-emerald-500/20 bg-emerald-500/[0.05]',
                                    )}
                                >
                                    <div className={cn(
                                        'text-[8px] font-bold uppercase',
                                        status === 'blocked' ? 'text-red-500' : status === 'warning' ? 'text-amber-500' : 'text-emerald-500',
                                    )}>
                                        {stringValue(check.code).replaceAll('_', ' ')}
                                    </div>
                                    <p className="mt-1 text-[9px] leading-relaxed text-text-main">{stringValue(check.message)}</p>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}
            {diagnostics.length > 0 && (
                <div className="mb-4">
                    <div className="mb-1.5 flex items-center gap-1.5 text-[9px] font-bold uppercase text-red-500">
                        <FileWarning size={11} />
                        Metadata diagnostics {diagnostics.length}
                    </div>
                    <div className="space-y-2">
                        {diagnostics.map((diagnostic, index) => (
                            <div
                                key={`${diagnostic.code}:${diagnostic.context}:${index}`}
                                className={cn(
                                    'rounded-md border px-3 py-2.5',
                                    diagnostic.level === 'error'
                                        ? 'border-red-500/20 bg-red-500/[0.05]'
                                        : 'border-amber-500/20 bg-amber-500/[0.05]',
                                )}
                            >
                                <div className="flex flex-wrap items-center gap-2">
                                    <span className={cn(
                                        'text-[9px] font-bold uppercase',
                                        diagnostic.level === 'error' ? 'text-red-500' : 'text-amber-500',
                                    )}>
                                        {diagnostic.code.replaceAll('_', ' ')}
                                    </span>
                                    {diagnostic.context && (
                                        <span className="rounded bg-black/[0.04] px-1.5 py-0.5 font-mono text-[8px] text-text-muted dark:bg-white/[0.05]">
                                            {diagnostic.context}
                                        </span>
                                    )}
                                </div>
                                <p className="mt-1 text-[10px] leading-relaxed text-text-main">{diagnostic.message}</p>
                                <p className="mt-1.5 text-[9px] leading-relaxed text-text-muted">
                                    <span className="font-bold uppercase text-text-main">Next step:</span> {diagnostic.guidance}
                                </p>
                            </div>
                        ))}
                    </div>
                </div>
            )}
            {(conflicts.length > 0 || risks.length > 0) && (
                <div className="mb-4 grid gap-3 lg:grid-cols-2">
                    <EvidenceList title="Conflicts" entries={conflicts} tone="danger" />
                    <EvidenceList title="Risks" entries={risks} tone="warn" />
                </div>
            )}
            <div className="mb-2 flex items-center justify-between">
                <div className="flex items-center gap-2 text-[10px] font-bold uppercase text-text-main">
                    <FolderOutput size={13} className="text-primary" />
                    Planned operations
                </div>
                <span className="font-mono text-[9px] text-text-muted">{actions.length} operations</span>
            </div>
            <div className="max-h-[340px] overflow-y-auto rounded-md border border-border-light bg-bg-panel">
                {actions.length === 0 ? (
                    <div className="px-3 py-5 text-center text-xs text-text-muted">No file operations in this plan.</div>
                ) : actions.map((action, index) => {
                    const type = stringValue(action.action) || stringValue(action.type) || 'operation';
                    const source = stringValue(action.source);
                    const destination = stringValue(action.destination) || stringValue(action.path);
                    const status = stringValue(action.status) || 'planned';
                    return (
                        <div key={`${type}:${destination}:${index}`} className="grid gap-1 border-b border-border-light px-3 py-2.5 last:border-b-0 md:grid-cols-[90px_minmax(0,1fr)_90px] md:items-center">
                            <span className="text-[9px] font-bold uppercase text-primary">{type.replaceAll('_', ' ')}</span>
                            <div className="min-w-0 font-mono text-[9px] text-text-muted">
                                {source && <div className="truncate" title={source}>{source}</div>}
                                {destination && <div className="truncate text-text-main" title={destination}>{destination}</div>}
                            </div>
                            <span className="text-[8px] font-bold uppercase text-text-muted md:text-right">{status}</span>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

function EvidenceList({ title, entries, tone }: {
    title: string;
    entries: MetadataRecord[];
    tone: 'danger' | 'warn';
}) {
    return (
        <div>
            <div className={cn('mb-1.5 text-[9px] font-bold uppercase', tone === 'danger' ? 'text-red-500' : 'text-amber-500')}>
                {title} {entries.length}
            </div>
            <div className="space-y-1.5">
                {entries.slice(0, 8).map((entry, index) => (
                    <div
                        key={`${title}:${index}`}
                        className={cn(
                            'rounded-md border px-2.5 py-2 text-[9px] leading-relaxed',
                            tone === 'danger'
                                ? 'border-red-500/20 bg-red-500/[0.05] text-red-500'
                                : 'border-amber-500/20 bg-amber-500/[0.05] text-amber-500',
                        )}
                    >
                        {stringValue(entry.message) || stringValue(entry.reason) || stringValue(entry.code) || JSON.stringify(entry)}
                    </div>
                ))}
            </div>
        </div>
    );
}

function ReviewMetric({ label, value, icon: Icon, tone = 'normal' }: {
    label: string;
    value: number;
    icon: LucideIcon;
    tone?: 'normal' | 'ok' | 'warn' | 'danger';
}) {
    const color = tone === 'ok' ? 'text-emerald-500' : tone === 'warn' ? 'text-amber-500' : tone === 'danger' ? 'text-red-500' : 'text-primary';
    return (
        <div className="rounded-lg border border-border-light bg-bg-surface px-3 py-2">
            <div className="flex items-center gap-1.5 text-[8px] font-bold uppercase text-text-muted">
                <Icon size={10} className={color} />
                {label}
            </div>
            <div className="mt-1 font-mono text-sm font-bold text-text-main">{value}</div>
        </div>
    );
}

function PlanMetric({ label, value, tone = 'normal' }: {
    label: string;
    value: number;
    tone?: 'normal' | 'ok' | 'warn' | 'danger';
}) {
    const color = tone === 'ok' ? 'text-emerald-500' : tone === 'warn' ? 'text-amber-500' : tone === 'danger' ? 'text-red-500' : 'text-text-main';
    return (
        <div className="rounded-md bg-black/[0.025] px-2 py-1.5 text-center dark:bg-white/[0.035]">
            <div className="text-[8px] uppercase text-text-muted">{label}</div>
            <div className={cn('mt-0.5 font-mono text-[10px] font-bold', color)}>{value}</div>
        </div>
    );
}
