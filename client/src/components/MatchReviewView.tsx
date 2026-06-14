import { useCallback, useEffect, useMemo, useState } from 'react';
import {
    AlertTriangle,
    Ban,
    CheckCircle2,
    FileQuestion,
    Film,
    Loader2,
    RefreshCw,
    Search,
    ShieldAlert,
    Tv,
    XCircle,
} from 'lucide-react';
import { toast } from 'sonner';

import { cn } from '../lib/utils';
import { fetchMatchReviews, planTask, resolveMatchReview } from '../lib/taskApi';
import {
    buildMatchReviewPayload,
    deriveMatchReviews,
    type MatchCandidateView,
    type MatchReviewView,
} from '../lib/matchReviewViewModel';
import type { MatchReviewRecord } from '../lib/types';
import { useSystemStatus } from '../lib/systemStatusContext';

interface MatchReviewViewProps {
    active: boolean;
}

interface ReviewChoice {
    tmdbId: string;
    mediaType: 'movie' | 'tv';
}

export function MatchReviewView({ active }: MatchReviewViewProps) {
    const [records, setRecords] = useState<MatchReviewRecord[]>([]);
    const [query, setQuery] = useState('');
    const [loading, setLoading] = useState(false);
    const [submitting, setSubmitting] = useState<string>();
    const [choices, setChoices] = useState<Record<string, ReviewChoice>>({});
    const { running, refresh: refreshSystemStatus } = useSystemStatus();

    const loadReviews = useCallback(async () => {
        setLoading(true);
        try {
            const response = await fetchMatchReviews();
            setRecords(response.reviews || []);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Match review queue unavailable');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (active) void loadReviews();
    }, [active, loadReviews]);

    const reviews = useMemo(() => deriveMatchReviews(records, query), [records, query]);
    const unresolvedCount = records.length;
    const reviewKey = (review: MatchReviewView) => `${review.taskId}:${review.itemId}`;

    const choiceFor = (review: MatchReviewView): ReviewChoice => choices[review.itemId] || {
        tmdbId: review.suggestedTmdbId ? String(review.suggestedTmdbId) : '',
        mediaType: review.suggestedMediaType,
    };

    const updateChoice = (review: MatchReviewView, patch: Partial<ReviewChoice>) => {
        setChoices(current => ({
            ...current,
            [review.itemId]: { ...choiceFor(review), ...patch },
        }));
    };

    const submitReview = async (review: MatchReviewView, execute: boolean) => {
        const choice = choiceFor(review);
        if (!/^\d+$/.test(choice.tmdbId.trim()) || Number(choice.tmdbId) <= 0) {
            toast.error('Enter a valid TMDB ID before continuing');
            return;
        }
        if (running) {
            toast.error('Another task is already running');
            return;
        }
        if (execute && !window.confirm([
            'Use this manual metadata match to generate an organize plan?',
            `Source: ${review.sourcePath}`,
            `TMDB: ${choice.tmdbId} (${choice.mediaType.toUpperCase()})`,
            'No files will change until the resulting locked plan is reviewed and confirmed.',
        ].join('\n'))) return;

        const key = reviewKey(review);
        setSubmitting(key);
        try {
            const payload = buildMatchReviewPayload(review, Number(choice.tmdbId), choice.mediaType, execute);
            await planTask({
                ...payload,
                dry_run: true,
                intended_strategy: execute ? 'organize' : 'audit',
            });
            await resolveMatchReview(review.taskId, review.itemId, {
                action: execute ? 'execute' : 'audit',
                tmdb_id: Number(choice.tmdbId),
                media_type: choice.mediaType,
            });
            setRecords(current => current.filter(record => `${record.task_id}:${record.item_id}` !== key));
            await refreshSystemStatus();
            toast.success(execute ? 'Confirmed match queued for organize planning' : 'Manual match queued for audit');
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Unable to start corrected task');
        } finally {
            setSubmitting(undefined);
        }
    };

    const ignoreReview = async (review: MatchReviewView) => {
        const key = reviewKey(review);
        if (!window.confirm(`Ignore this unresolved match?\n${review.sourcePath}\n\nThe source files will not be changed.`)) return;
        setSubmitting(key);
        try {
            await resolveMatchReview(review.taskId, review.itemId, { action: 'ignored' });
            setRecords(current => current.filter(record => `${record.task_id}:${record.item_id}` !== key));
            toast.success('Match review dismissed');
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Unable to ignore match review');
        } finally {
            setSubmitting(undefined);
        }
    };

    const rejectReview = async (review: MatchReviewView) => {
        const choice = choiceFor(review);
        if (!/^\d+$/.test(choice.tmdbId.trim()) || Number(choice.tmdbId) <= 0) {
            toast.error('Select or enter the TMDB candidate to reject');
            return;
        }
        if (!window.confirm([
            `Reject TMDB ${choice.tmdbId} for "${review.parsedTitle}"?`,
            'Future automatic searches for this title will skip this candidate.',
            'Source files will not be changed. You can undo this rule in Settings.',
        ].join('\n'))) return;
        const key = reviewKey(review);
        setSubmitting(key);
        try {
            await resolveMatchReview(review.taskId, review.itemId, {
                action: 'rejected',
                tmdb_id: Number(choice.tmdbId),
                media_type: choice.mediaType,
            });
            setRecords(current => current.filter(record => `${record.task_id}:${record.item_id}` !== key));
            toast.success('Candidate rejected and remembered');
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Unable to reject candidate');
        } finally {
            setSubmitting(undefined);
        }
    };

    return (
        <section className="h-full min-h-0 overflow-hidden rounded-3xl border border-glass-border glass-panel-pro shadow-xl flex flex-col">
            <header className="shrink-0 border-b border-border-light px-6 py-5">
                <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                        <div className="flex items-center gap-2">
                            <ShieldAlert size={18} className="text-amber-500" />
                            <h2 className="text-lg font-bold text-text-main">Match Review</h2>
                        </div>
                        <p className="mt-1 max-w-2xl text-xs leading-relaxed text-text-muted">
                            Low-confidence matches are blocked from execution until you choose a candidate or enter a TMDB ID.
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={() => void loadReviews()}
                        disabled={loading}
                        className="inline-flex h-9 items-center gap-2 rounded-lg border border-border-light bg-bg-surface px-3 text-[10px] font-bold uppercase text-text-muted hover:text-primary disabled:opacity-50"
                    >
                        <RefreshCw size={14} className={cn(loading && 'animate-spin')} />
                        Refresh
                    </button>
                </div>

                <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-5">
                        <div>
                            <div className="text-[9px] font-bold uppercase tracking-wider text-text-muted">Needs confirmation</div>
                            <div className="mt-1 font-mono text-xl font-bold text-amber-500">{unresolvedCount}</div>
                        </div>
                        <div className="h-10 w-px bg-border-light" />
                        <div className="flex items-center gap-2 text-[10px] text-text-muted">
                            <AlertTriangle size={13} className="text-amber-500" />
                            Automatic execution remains blocked
                        </div>
                    </div>
                    <label className="flex h-10 min-w-[260px] flex-1 items-center gap-2 rounded-lg border border-border-light bg-bg-surface px-3 lg:max-w-sm">
                        <Search size={14} className="text-text-muted" />
                        <input
                            value={query}
                            onChange={event => setQuery(event.target.value)}
                            placeholder="Search source, title, provider, reason..."
                            className="min-w-0 flex-1 bg-transparent text-xs outline-none placeholder:text-text-muted/60"
                        />
                    </label>
                </div>
            </header>

            <div className="flex-1 min-h-0 overflow-y-auto p-4 md:p-5">
                {reviews.length === 0 ? (
                    <div className="h-full min-h-[280px] flex flex-col items-center justify-center gap-3 text-text-muted">
                        {loading ? <Loader2 size={28} className="animate-spin" /> : <CheckCircle2 size={30} className="text-emerald-500/70" />}
                        <p className="text-sm font-semibold">{loading ? 'Loading review queue...' : 'No matches require confirmation'}</p>
                    </div>
                ) : (
                    <div className="space-y-4">
                        {reviews.map(review => (
                            <ReviewItem
                                key={`${review.taskId}:${review.itemId}`}
                                review={review}
                                choice={choiceFor(review)}
                                submitting={submitting === reviewKey(review)}
                                busy={running}
                                onChoice={(patch) => updateChoice(review, patch)}
                                onAudit={() => void submitReview(review, false)}
                                onExecute={() => void submitReview(review, true)}
                                onReject={() => void rejectReview(review)}
                                onIgnore={() => void ignoreReview(review)}
                            />
                        ))}
                    </div>
                )}
            </div>
        </section>
    );
}

function ReviewItem({ review, choice, submitting, busy, onChoice, onAudit, onExecute, onReject, onIgnore }: {
    review: MatchReviewView;
    choice: ReviewChoice;
    submitting: boolean;
    busy: boolean;
    onChoice: (patch: Partial<ReviewChoice>) => void;
    onAudit: () => void;
    onExecute: () => void;
    onReject: () => void;
    onIgnore: () => void;
}) {
    const confidence = review.match.confidence || 'none';
    const score = typeof review.match.score === 'number' ? review.match.score : undefined;
    const selectedId = Number(choice.tmdbId);

    return (
        <article className="overflow-hidden rounded-lg border border-border-light bg-bg-panel">
            <div className="grid gap-5 p-4 lg:grid-cols-[minmax(230px,0.8fr)_minmax(0,1.7fr)]">
                <div className="min-w-0">
                    <div className="flex items-start gap-3">
                        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-amber-500/10 text-amber-500">
                            <FileQuestion size={18} />
                        </span>
                        <div className="min-w-0">
                            <h3 className="truncate text-sm font-bold text-text-main">{review.parsedTitle}</h3>
                            <p className="mt-1 break-all font-mono text-[9px] leading-relaxed text-text-muted">{review.sourcePath}</p>
                        </div>
                    </div>

                    <div className="mt-4 space-y-2 border-l-2 border-amber-500/40 pl-3">
                        <Evidence label="Provider" value={review.match.provider || 'unknown'} />
                        <Evidence label="Confidence" value={confidence} tone="warning" />
                        <Evidence label="Score" value={score === undefined ? 'not available' : score.toFixed(2)} tone={score !== undefined && score < 0.55 ? 'danger' : 'warning'} />
                        <Evidence label="Reason" value={review.match.review_reason || review.match.reason || 'review required'} />
                        {review.match.matched_title && <Evidence label="Matched title" value={review.match.matched_title} />}
                        {review.error && <Evidence label="Blocked" value={review.error} tone="danger" />}
                    </div>
                </div>

                <div className="min-w-0">
                    <div className="text-[10px] font-bold uppercase tracking-wider text-text-muted">Candidate evidence</div>
                    {review.candidates.length === 0 ? (
                        <div className="mt-3 rounded-lg border border-dashed border-border-light px-4 py-5 text-xs text-text-muted">
                            No reliable candidate was returned. Enter a TMDB ID manually below.
                        </div>
                    ) : (
                        <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                            {review.candidates.map(candidate => (
                                <CandidateButton
                                    key={`${candidate.mediaType || review.suggestedMediaType}:${candidate.id}`}
                                    candidate={candidate}
                                    selected={selectedId === candidate.id}
                                    onSelect={() => onChoice({
                                        tmdbId: String(candidate.id),
                                        mediaType: candidate.mediaType || choice.mediaType,
                                    })}
                                />
                            ))}
                        </div>
                    )}
                </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border-light bg-black/[0.025] px-4 py-3 dark:bg-black/10">
                <div className="flex flex-wrap items-center gap-2">
                    <div className="flex rounded-lg border border-border-light bg-bg-surface p-1">
                        <button
                            type="button"
                            onClick={() => onChoice({ mediaType: 'movie' })}
                            className={cn('inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[10px] font-bold', choice.mediaType === 'movie' ? 'bg-blue-500/15 text-blue-500' : 'text-text-muted')}
                        >
                            <Film size={12} /> Movie
                        </button>
                        <button
                            type="button"
                            onClick={() => onChoice({ mediaType: 'tv' })}
                            className={cn('inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[10px] font-bold', choice.mediaType === 'tv' ? 'bg-fuchsia-500/15 text-fuchsia-500' : 'text-text-muted')}
                        >
                            <Tv size={12} /> TV
                        </button>
                    </div>
                    <input
                        value={choice.tmdbId}
                        onChange={event => onChoice({ tmdbId: event.target.value })}
                        inputMode="numeric"
                        placeholder="TMDB ID"
                        className="h-9 w-32 rounded-lg border border-border-light bg-bg-surface px-3 font-mono text-xs text-text-main outline-none focus:border-primary"
                    />
                </div>

                <div className="flex items-center gap-2">
                    <button
                        type="button"
                        disabled={submitting}
                        onClick={onIgnore}
                        className="inline-flex h-9 items-center gap-2 rounded-lg px-3 text-[10px] font-bold uppercase text-text-muted hover:bg-red-500/10 hover:text-red-500 disabled:opacity-40"
                    >
                        <XCircle size={13} />
                        Dismiss
                    </button>
                    <button
                        type="button"
                        disabled={submitting || !/^\d+$/.test(choice.tmdbId.trim())}
                        onClick={onReject}
                        className="inline-flex h-9 items-center gap-2 rounded-lg border border-red-500/25 px-3 text-[10px] font-bold uppercase text-red-500 hover:bg-red-500/10 disabled:opacity-40"
                    >
                        <Ban size={13} />
                        Reject candidate
                    </button>
                    <button
                        type="button"
                        disabled={submitting || busy}
                        onClick={onAudit}
                        className="inline-flex h-9 items-center gap-2 rounded-lg border border-border-light bg-bg-surface px-3 text-[10px] font-bold uppercase text-text-main hover:border-primary/50 disabled:opacity-40"
                    >
                        {submitting ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                        Audit again
                    </button>
                    <button
                        type="button"
                        disabled={submitting || busy}
                        onClick={onExecute}
                        className="inline-flex h-9 items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/15 px-3 text-[10px] font-bold uppercase text-amber-500 hover:bg-amber-500/25 disabled:opacity-40"
                    >
                        <ShieldAlert size={13} />
                        Confirm & organize
                    </button>
                </div>
            </div>
        </article>
    );
}

function CandidateButton({ candidate, selected, onSelect }: {
    candidate: MatchCandidateView;
    selected: boolean;
    onSelect: () => void;
}) {
    const rejected = candidate.decision === 'year_mismatch'
        || candidate.decision === 'low_similarity'
        || candidate.decision === 'user_rejected';
    return (
        <button
            type="button"
            onClick={onSelect}
            className={cn(
                'min-h-[156px] rounded-lg border p-3 text-left transition-colors',
                selected
                    ? 'border-primary bg-primary/10'
                    : rejected
                        ? 'border-red-500/20 bg-red-500/[0.035] hover:border-red-500/40'
                        : 'border-border-light bg-bg-surface hover:border-primary/35',
            )}
        >
            <div className="flex items-start justify-between gap-2">
                <span className="line-clamp-2 text-xs font-bold text-text-main">{candidate.title}</span>
                {selected && <CheckCircle2 size={14} className="shrink-0 text-primary" />}
            </div>
            <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[9px] text-text-muted">
                <span>ID {candidate.id}</span>
                {candidate.mediaType && <span>{candidate.mediaType.toUpperCase()}</span>}
                {candidate.year && <span>{candidate.year}</span>}
                {candidate.score !== undefined && <span className={candidate.score < 0.55 ? 'text-amber-500' : ''}>overall {candidate.score.toFixed(2)}</span>}
            </div>
            <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5">
                <ScoreEvidence label="Title" score={candidate.titleSimilarity} />
                <ScoreEvidence label="Tokens" score={candidate.tokenOverlap} />
                <StatusEvidence label="Year" status={candidate.yearStatus} />
                <StatusEvidence label="Type" status={candidate.mediaTypeStatus} />
            </div>
            <div className={cn('mt-2 text-[9px] font-semibold', rejected ? 'text-red-500' : candidate.decision === 'selected' ? 'text-emerald-500' : 'text-text-muted')}>
                {(candidate.decision || 'candidate').replaceAll('_', ' ')}
            </div>
            {candidate.matchedTitle && (
                <div className="mt-1 truncate text-[9px] text-text-muted" title={candidate.matchedTitle}>
                    matched {candidate.matchedField || 'title'}: {candidate.matchedTitle}
                </div>
            )}
            {candidate.hardBlockers.length > 0 && (
                <div className="mt-1 truncate text-[9px] text-red-500" title={candidate.hardBlockers.join(', ')}>
                    blocked: {candidate.hardBlockers.map(value => value.replaceAll('_', ' ')).join(', ')}
                </div>
            )}
        </button>
    );
}

function ScoreEvidence({ label, score }: { label: string; score?: number }) {
    const percentage = score === undefined ? 0 : Math.round(score * 100);
    return (
        <div>
            <div className="flex items-center justify-between font-mono text-[8px] text-text-muted">
                <span>{label}</span>
                <span>{score === undefined ? 'n/a' : `${percentage}%`}</span>
            </div>
            <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-border-light">
                <div
                    className={cn('h-full rounded-full', percentage >= 75 ? 'bg-emerald-500' : percentage >= 55 ? 'bg-amber-500' : 'bg-red-500')}
                    style={{ width: `${percentage}%` }}
                />
            </div>
        </div>
    );
}

function StatusEvidence({ label, status }: { label: string; status?: string }) {
    const positive = status === 'exact' || status === 'compatible' || status === 'bridged_by_alias';
    const negative = status === 'mismatch';
    return (
        <div className="flex items-center justify-between gap-2 font-mono text-[8px] text-text-muted">
            <span>{label}</span>
            <span className={cn(positive && 'text-emerald-500', negative && 'text-red-500')}>
                {(status || 'n/a').replaceAll('_', ' ')}
            </span>
        </div>
    );
}

function Evidence({ label, value, tone = 'neutral' }: {
    label: string;
    value: string;
    tone?: 'neutral' | 'warning' | 'danger';
}) {
    return (
        <div className="grid grid-cols-[76px_minmax(0,1fr)] gap-2 text-[10px]">
            <span className="uppercase text-text-muted">{label}</span>
            <span className={cn('break-words font-semibold', tone === 'danger' ? 'text-red-500' : tone === 'warning' ? 'text-amber-500' : 'text-text-main')}>{value}</span>
        </div>
    );
}
