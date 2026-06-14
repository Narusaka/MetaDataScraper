import { useMemo, useState } from 'react';
import {
    AlertCircle,
    CheckCircle2,
    Database,
    FileText,
    Film,
    FolderInput,
    Image,
    Loader2,
    Play,
    ScanSearch,
    ShieldCheck,
    Subtitles,
    Tv,
    Video,
    X,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { toast } from 'sonner';

import { FolderPicker } from './FolderPicker';
import { planTask, scanLibrary } from '../lib/taskApi';
import {
    buildLibraryAuditPayload,
    filterLibraryScanItems,
} from '../lib/libraryScanViewModel';
import type { LibraryScanFilter } from '../lib/libraryScanViewModel';
import type { LibraryScanItem, LibraryScanResponse } from '../lib/types';
import { cn } from '../lib/utils';
import { useSystemStatus } from '../lib/systemStatusContext';

type ScanMode = 'auto' | 'single' | 'batch';

export function LibraryScanView({ active }: { active: boolean }) {
    const [path, setPath] = useState(() => localStorage.getItem('last_path') || '');
    const [mode, setMode] = useState<ScanMode>('auto');
    const [useLocalNfo, setUseLocalNfo] = useState(true);
    const [result, setResult] = useState<LibraryScanResponse>();
    const [loading, setLoading] = useState(false);
    const [planningId, setPlanningId] = useState<string>();
    const [filter, setFilter] = useState<LibraryScanFilter>('all');
    const [showPicker, setShowPicker] = useState(false);
    const { running, refresh } = useSystemStatus();

    const items = useMemo(() => {
        return filterLibraryScanItems(result?.items || [], filter);
    }, [filter, result]);

    const runScan = async () => {
        const normalized = path.trim();
        if (!normalized) {
            toast.error('Choose a media directory first');
            return;
        }
        setLoading(true);
        try {
            const response = await scanLibrary({
                path: normalized,
                mode,
                use_local_nfo: useLocalNfo,
            });
            setResult(response);
            setFilter(response.summary.review || response.summary.quarantined ? 'review' : 'all');
            localStorage.setItem('last_path', response.root);
            toast.success(`Scanned ${response.summary.items} media items without changing files`);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Library scan failed');
        } finally {
            setLoading(false);
        }
    };

    const createAuditPlan = async (item: LibraryScanItem) => {
        if (running) {
            toast.error('Another task is already running');
            return;
        }
        if (item.kind !== 'directory') {
            toast.error('Loose files must be planned from their containing directory');
            return;
        }
        setPlanningId(item.id);
        try {
            await planTask(buildLibraryAuditPayload(item, useLocalNfo));
            await refresh();
            toast.success('Locked audit plan queued');
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Unable to create audit plan');
        } finally {
            setPlanningId(undefined);
        }
    };

    if (!active) return null;

    return (
        <>
            <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-glass-border glass-panel-pro shadow-xl">
                <header className="shrink-0 border-b border-border-light px-4 py-4 md:px-6">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                            <div className="flex items-center gap-2">
                                <ScanSearch size={18} className="text-primary" />
                                <h2 className="text-lg font-bold text-text-main">Library Scan</h2>
                                <span className="rounded-md border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-[9px] font-bold uppercase text-emerald-500">
                                    Read only
                                </span>
                            </div>
                            <p className="mt-1 text-xs text-text-muted">
                                Inventory and validate local media before metadata matching or file operations.
                            </p>
                        </div>
                    </div>

                    <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(280px,1fr)_auto_auto]">
                        <div className="flex h-11 min-w-0 items-center gap-2 rounded-lg border border-border-light bg-bg-surface px-3 focus-within:border-primary/50">
                            <input
                                value={path}
                                onChange={event => setPath(event.target.value)}
                                onKeyDown={event => {
                                    if (event.key === 'Enter') void runScan();
                                }}
                                placeholder="/path/to/media/library"
                                className="min-w-0 flex-1 bg-transparent font-mono text-xs text-text-main outline-none"
                            />
                            <button
                                type="button"
                                onClick={() => setShowPicker(true)}
                                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-text-muted hover:bg-primary/10 hover:text-primary"
                                title="Choose directory"
                            >
                                <FolderInput size={15} />
                            </button>
                        </div>
                        <div className="grid grid-cols-3 rounded-lg border border-border-light bg-bg-surface p-1">
                            {(['auto', 'single', 'batch'] as ScanMode[]).map(value => (
                                <button
                                    key={value}
                                    type="button"
                                    onClick={() => setMode(value)}
                                    className={cn(
                                        'h-8 min-w-[68px] rounded-md px-2 text-[9px] font-bold uppercase',
                                        mode === value ? 'bg-primary text-white' : 'text-text-muted hover:text-text-main',
                                    )}
                                >
                                    {value}
                                </button>
                            ))}
                        </div>
                        <button
                            type="button"
                            onClick={() => void runScan()}
                            disabled={loading || !path.trim()}
                            className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-primary px-5 text-[10px] font-bold uppercase text-white hover:brightness-110 disabled:opacity-40"
                        >
                            {loading ? <Loader2 size={14} className="animate-spin" /> : <ScanSearch size={14} />}
                            Scan
                        </button>
                    </div>

                    <label className="mt-3 inline-flex items-center gap-2 text-[10px] text-text-muted">
                        <input
                            type="checkbox"
                            checked={useLocalNfo}
                            onChange={event => setUseLocalNfo(event.target.checked)}
                            className="accent-primary"
                        />
                        Read local NFO identifiers during inventory
                    </label>
                </header>

                {!result ? (
                    <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center text-text-muted">
                        <span className="flex h-14 w-14 items-center justify-center rounded-lg border border-border-light bg-bg-surface">
                            <Database size={24} />
                        </span>
                        <div className="text-sm font-semibold text-text-main">Choose a library root to inspect</div>
                        <p className="max-w-lg text-xs leading-relaxed">
                            The scan reads filenames, NFO identifiers, episode markers and existing artwork. It does not contact metadata providers or modify files.
                        </p>
                    </div>
                ) : (
                    <>
                        <div className="shrink-0 border-b border-border-light px-4 py-3 md:px-6">
                            <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
                                <SummaryMetric label="Items" value={result.summary.items} icon={Database} />
                                <SummaryMetric label="Ready" value={result.summary.ready} icon={CheckCircle2} tone="ok" />
                                <SummaryMetric label="Review" value={result.summary.review + result.summary.quarantined} icon={AlertCircle} tone="warn" />
                                <SummaryMetric label="Videos" value={result.summary.videos} icon={Video} />
                                <SummaryMetric label="NFO IDs" value={result.summary.with_tmdb_id} icon={FileText} />
                                <SummaryMetric label="Mode" value={result.mode} icon={ShieldCheck} />
                            </div>
                            <div className="mt-3 flex flex-wrap items-center gap-2">
                                {([
                                    ['all', `All ${result.summary.items}`],
                                    ['ready', `Ready ${result.summary.ready}`],
                                    ['review', `Review ${result.summary.review + result.summary.quarantined}`],
                                    ['nfo', `NFO ${result.summary.with_tmdb_id}`],
                                ] as Array<[LibraryScanFilter, string]>).map(([value, label]) => (
                                    <button
                                        key={value}
                                        type="button"
                                        onClick={() => setFilter(value)}
                                        className={cn(
                                            'h-7 rounded-md border px-2.5 text-[9px] font-bold uppercase',
                                            filter === value
                                                ? 'border-primary/40 bg-primary/10 text-primary'
                                                : 'border-border-light text-text-muted hover:text-text-main',
                                        )}
                                    >
                                        {label}
                                    </button>
                                ))}
                                <span className="ml-auto truncate font-mono text-[9px] text-text-muted" title={result.root}>
                                    {result.root}
                                </span>
                            </div>
                        </div>

                        <div className="min-h-0 flex-1 overflow-y-auto p-3 md:p-4">
                            {items.length === 0 ? (
                                <div className="flex h-full min-h-[220px] items-center justify-center text-xs text-text-muted">
                                    No items match this filter.
                                </div>
                            ) : (
                                <div className="grid gap-3 xl:grid-cols-2">
                                    {items.map(item => (
                                        <ScanItem
                                            key={item.id}
                                            item={item}
                                            planning={planningId === item.id}
                                            disabled={running || !!planningId}
                                            onPlan={() => void createAuditPlan(item)}
                                        />
                                    ))}
                                </div>
                            )}
                        </div>
                    </>
                )}
            </section>

            {showPicker && (
                <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
                    <div className="flex h-[min(680px,88vh)] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-border-light bg-bg-panel shadow-2xl">
                        <div className="flex h-12 shrink-0 items-center justify-between border-b border-border-light px-4">
                            <span className="text-xs font-bold">Choose library root</span>
                            <button
                                type="button"
                                onClick={() => setShowPicker(false)}
                                className="flex h-8 w-8 items-center justify-center rounded-md text-text-muted hover:bg-red-500/10 hover:text-red-500"
                            >
                                <X size={15} />
                            </button>
                        </div>
                        <FolderPicker
                            initialPath={path}
                            onSelect={selected => setPath(selected)}
                            className="min-h-0 flex-1"
                        />
                        <div className="flex shrink-0 justify-end border-t border-border-light p-3">
                            <button
                                type="button"
                                onClick={() => setShowPicker(false)}
                                className="h-9 rounded-md bg-primary px-4 text-[10px] font-bold uppercase text-white"
                            >
                                Use folder
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
}

function SummaryMetric({ label, value, icon: Icon, tone = 'normal' }: {
    label: string;
    value: number | string;
    icon: LucideIcon;
    tone?: 'normal' | 'ok' | 'warn';
}) {
    return (
        <div className="min-w-0 rounded-lg border border-border-light bg-bg-surface px-2.5 py-2">
            <div className="flex items-center gap-1.5 text-[8px] font-bold uppercase text-text-muted">
                <Icon size={10} className={tone === 'ok' ? 'text-emerald-500' : tone === 'warn' ? 'text-amber-500' : 'text-primary'} />
                {label}
            </div>
            <div className="mt-1 truncate font-mono text-sm font-bold text-text-main">{value}</div>
        </div>
    );
}

function ScanItem({ item, planning, disabled, onPlan }: {
    item: LibraryScanItem;
    planning: boolean;
    disabled: boolean;
    onPlan: () => void;
}) {
    const TypeIcon = item.media_type === 'tv' ? Tv : Film;
    const issueTone = item.status === 'ready'
        ? 'border-emerald-500/20'
        : item.status === 'quarantined'
            ? 'border-red-500/30'
            : 'border-amber-500/25';
    const artworkTotal = Object.values(item.artwork).reduce((sum, value) => sum + value, 0);

    return (
        <article className={cn('rounded-lg border bg-bg-panel p-3', issueTone)}>
            <div className="flex items-start gap-3">
                <span className={cn(
                    'flex h-10 w-10 shrink-0 items-center justify-center rounded-lg',
                    item.media_type === 'tv' ? 'bg-fuchsia-500/10 text-fuchsia-500' : 'bg-blue-500/10 text-blue-500',
                )}>
                    <TypeIcon size={18} />
                </span>
                <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <h3 className="min-w-0 truncate text-sm font-bold text-text-main">{item.parsed_title || item.name}</h3>
                        {item.year && <span className="font-mono text-[9px] text-text-muted">{item.year}</span>}
                        <span className={cn(
                            'rounded-md px-1.5 py-0.5 text-[8px] font-bold uppercase',
                            item.status === 'ready'
                                ? 'bg-emerald-500/10 text-emerald-500'
                                : item.status === 'review'
                                    ? 'bg-amber-500/10 text-amber-500'
                                    : 'bg-red-500/10 text-red-500',
                        )}>
                            {item.status}
                        </span>
                    </div>
                    <p className="mt-1 truncate font-mono text-[9px] text-text-muted" title={item.path}>{item.path}</p>
                </div>
            </div>

            <div className="mt-3 grid grid-cols-5 gap-1.5">
                <AssetMetric icon={Video} label="Video" value={item.video_count} />
                <AssetMetric icon={Subtitles} label="Subs" value={item.subtitle_count} />
                <AssetMetric icon={FileText} label="NFO" value={item.nfo_count} />
                <AssetMetric icon={Image} label="Art" value={artworkTotal} />
                <AssetMetric icon={Database} label="TMDB" value={item.tmdb_id || '—'} />
            </div>

            {item.issues.length > 0 && (
                <div className="mt-3 space-y-2">
                    {item.issues.slice(0, 3).map((issue, index) => (
                        <div
                            key={`${issue.code}:${issue.episode || index}`}
                            className={cn(
                                'rounded-md border px-2.5 py-2 text-[10px] leading-relaxed',
                                issue.level === 'error'
                                    ? 'border-red-500/20 bg-red-500/[0.05] text-red-500'
                                    : 'border-amber-500/20 bg-amber-500/[0.05] text-amber-500',
                            )}
                        >
                            <div className="font-bold">{issue.message}</div>
                            {issue.sources?.map(source => (
                                <div key={source} className="mt-1 truncate font-mono text-[9px] text-text-muted" title={source}>
                                    {source.split('/').slice(-2).join('/')}
                                </div>
                            ))}
                        </div>
                    ))}
                </div>
            )}

            <div className="mt-3 flex items-center justify-between gap-3 border-t border-border-light pt-3">
                <div className="text-[9px] text-text-muted">
                    parse <span className="font-mono font-bold text-text-main">{item.parse_confidence || 'none'}</span>
                    {item.episode_count > 0 && <> · {item.episode_count} episodes</>}
                </div>
                <button
                    type="button"
                    onClick={onPlan}
                    disabled={disabled || item.kind !== 'directory' || item.status === 'quarantined'}
                    className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-3 text-[9px] font-bold uppercase text-primary hover:bg-primary/15 disabled:opacity-35"
                    title="Generate a locked audit plan; no files will be changed"
                >
                    {planning ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
                    Audit plan
                </button>
            </div>
        </article>
    );
}

function AssetMetric({ icon: Icon, label, value }: {
    icon: LucideIcon;
    label: string;
    value: number | string;
}) {
    return (
        <div className="min-w-0 rounded-md bg-black/[0.025] px-2 py-1.5 text-center dark:bg-white/[0.035]">
            <div className="flex items-center justify-center gap-1 text-[8px] uppercase text-text-muted">
                <Icon size={9} />
                {label}
            </div>
            <div className="mt-0.5 truncate font-mono text-[10px] font-bold text-text-main">{value}</div>
        </div>
    );
}
