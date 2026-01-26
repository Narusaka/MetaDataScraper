
import { useState, useEffect } from 'react';
import { Play, ShieldAlert, Cpu, Eye, FolderInput, Copy, FileImage, FileText } from 'lucide-react';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/language';
import { FolderPicker } from './FolderPicker';
import { TerminalView } from './TerminalView';

interface DashboardProps {
    isRunning: boolean;
    onStart: (config: any) => void;
}

type Strategy = 'audit' | 'organize' | 'copy';

export function Dashboard({ isRunning, onStart }: DashboardProps) {
    const { t } = useTranslation();
    const [selectedPath, setSelectedPath] = useState("");
    const [strategy, setStrategy] = useState<Strategy>(() => (localStorage.getItem('task_strategy') as Strategy) || 'audit');
    const [workers, setWorkers] = useState(() => parseInt(localStorage.getItem('task_workers') || "4"));

    // Advanced Options
    const [useLocalNfo, setUseLocalNfo] = useState(() => localStorage.getItem('task_local_nfo') === 'true');
    const [extraImages, setExtraImages] = useState(() => localStorage.getItem('task_extra_images') === 'true');
    const [outputPath, setOutputPath] = useState(() => localStorage.getItem('task_output_path') || "");
    const [mediaType, setMediaType] = useState(() => localStorage.getItem('task_media_type') || "");
    const [tmdbId, setTmdbId] = useState(() => localStorage.getItem('task_tmdb_id') || "");
    const [searchMode, setSearchMode] = useState<'smart' | 'tmdb_only'>(() => (localStorage.getItem('task_search_mode') as 'smart' | 'tmdb_only') || 'smart');
    const [enableFallback, setEnableFallback] = useState(() => localStorage.getItem('task_enable_fallback') !== 'false');

    useEffect(() => localStorage.setItem('task_strategy', strategy), [strategy]);
    useEffect(() => localStorage.setItem('task_workers', workers.toString()), [workers]);
    useEffect(() => localStorage.setItem('task_local_nfo', useLocalNfo.toString()), [useLocalNfo]);
    useEffect(() => localStorage.setItem('task_extra_images', extraImages.toString()), [extraImages]);
    useEffect(() => localStorage.setItem('task_output_path', outputPath), [outputPath]);
    useEffect(() => localStorage.setItem('task_media_type', mediaType), [mediaType]);
    useEffect(() => localStorage.setItem('task_tmdb_id', tmdbId), [tmdbId]);
    useEffect(() => localStorage.setItem('task_search_mode', searchMode), [searchMode]);
    useEffect(() => localStorage.setItem('task_enable_fallback', enableFallback.toString()), [enableFallback]);

    const handleStart = () => {
        onStart({
            input_dir: selectedPath,
            workers,
            dry_run: strategy === 'audit',
            inplace: strategy === 'organize',
            copy_mode: strategy === 'copy',
            output_dir: strategy === 'copy' ? outputPath : null,
            use_local_nfo: useLocalNfo,
            extra_images: extraImages,
            media_type: mediaType || null,
            tmdb_id: tmdbId ? parseInt(tmdbId) : null,
            search_mode: searchMode,
            enable_fallback: enableFallback
        });
    };

    return (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 h-full pb-6">
            {/* Left: Config & Files */}
            <div className="flex flex-col gap-6 lg:col-span-1 min-w-0">
                <div className="p-6 glass-panel rounded-xl space-y-6">
                    <h3 className="font-semibold flex items-center gap-2 text-lg text-primary">
                        <Cpu className="w-5 h-5" />
                        {t('task_config')}
                    </h3>

                    {/* Path Selection Display */}
                    <div className="text-sm font-medium text-secondary truncate">
                        Target: <span className="font-mono text-foreground opacity-80">{selectedPath || "None"}</span>
                    </div>

                    {/* Strategy Selector */}
                    <div className="space-y-3">
                        <label className="text-xs text-secondary font-medium uppercase tracking-wider pl-1">{t('strategy')}</label>
                        <div className="grid grid-cols-1 gap-2">
                            <StrategyCard
                                active={strategy === 'audit'}
                                onClick={() => setStrategy('audit')}
                                icon={<Eye className="w-5 h-5" />}
                                title={t('mode_audit')}
                                desc={t('mode_audit_desc')}
                            />
                            <StrategyCard
                                active={strategy === 'organize'}
                                onClick={() => setStrategy('organize')}
                                icon={<FolderInput className="w-5 h-5" />}
                                title={t('mode_organize')}
                                desc={t('mode_organize_desc')}
                                warn
                            />
                            <StrategyCard
                                active={strategy === 'copy'}
                                onClick={() => setStrategy('copy')}
                                icon={<Copy className="w-5 h-5" />}
                                title={t('mode_copy')}
                                desc={t('mode_copy_desc')}
                            />
                        </div>
                    </div>

                    {/* Dynamic Output Path Input */}
                    {strategy === 'copy' && (
                        <div className="animate-in fade-in slide-in-from-top-2">
                            <label className="text-xs text-secondary font-medium uppercase tracking-wider pl-1 mb-1 block">{t('path_output')}</label>
                            <input
                                type="text"
                                className="w-full glass-panel bg-black/10 px-3 py-2 rounded-lg border-border/30 focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm"
                                placeholder="/path/to/output"
                                value={outputPath}
                                onChange={(e) => setOutputPath(e.target.value)}
                            />
                        </div>
                    )}

                    {/* Media Type & TMDB ID */}
                    <div className="flex flex-col gap-6 py-6 border-t border-border/30">
                        <div className="space-y-3">
                            <label className="text-sm font-bold text-secondary px-1 uppercase tracking-wider">{t('media_settings')}</label>
                            <div className="grid grid-cols-3 gap-3">
                                {['', 'movie', 'tv'].map(type => (
                                    <button
                                        key={type}
                                        onClick={() => setMediaType(type)}
                                        className={cn(
                                            "py-3 px-4 rounded-xl text-sm font-bold border transition-all uppercase tracking-tight",
                                            mediaType === type
                                                ? "bg-primary text-white border-primary shadow-lg shadow-primary/30 scale-[1.02]"
                                                : "bg-black/5 dark:bg-black/20 text-secondary border-border/20 hover:border-primary/50"
                                        )}
                                    >
                                        {type || "AUTO"}
                                    </button>
                                ))}
                            </div>
                        </div>

                        <div className="flex flex-col gap-2">
                            <label className="text-sm font-bold text-secondary px-1 uppercase tracking-wider">
                                TMDB ID (Optional)
                            </label>
                            <input
                                type="number"
                                placeholder="Force specific ID (Single Item)"
                                value={tmdbId}
                                onChange={(e) => setTmdbId(e.target.value)}
                                className="w-full glass-panel bg-black/5 dark:bg-black/20 px-4 py-3.5 rounded-xl border-border/20 focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none text-base placeholder:text-muted/50 transition-all shadow-inner"
                            />
                        </div>
                    </div>

                    {/* Search & Fallback Strategy */}
                    <div className="flex flex-col gap-4 py-6 border-t border-border/30">
                        <label className="text-sm font-bold text-secondary px-1 uppercase tracking-wider">{t('search_settings')}</label>
                        <div className="grid grid-cols-1 gap-2.5">
                            <button
                                onClick={() => setSearchMode('smart')}
                                className={cn(
                                    "flex items-center justify-between p-4 rounded-xl border transition-all text-sm font-semibold",
                                    searchMode === 'smart' ? "bg-primary/5 border-primary text-primary shadow-sm" : "bg-black/5 dark:bg-black/20 border-border/20 text-secondary hover:border-border/50"
                                )}
                            >
                                <span>{t('search_mode_smart')}</span>
                                <div className={cn("w-3 h-3 rounded-full shadow-inner transition-all", searchMode === 'smart' ? "bg-primary scale-110" : "bg-black/10 dark:bg-black/40")} />
                            </button>
                            <button
                                onClick={() => setSearchMode('tmdb_only')}
                                className={cn(
                                    "flex items-center justify-between p-4 rounded-xl border transition-all text-sm font-semibold",
                                    searchMode === 'tmdb_only' ? "bg-primary/5 border-primary text-primary shadow-sm" : "bg-black/5 dark:bg-black/20 border-border/20 text-secondary hover:border-border/50"
                                )}
                            >
                                <span>{t('search_mode_tmdb')}</span>
                                <div className={cn("w-3 h-3 rounded-full shadow-inner transition-all", searchMode === 'tmdb_only' ? "bg-primary scale-110" : "bg-black/10 dark:bg-black/40")} />
                            </button>
                        </div>

                        <div
                            onClick={() => setEnableFallback(!enableFallback)}
                            className={cn(
                                "flex items-center gap-4 p-4 rounded-xl border cursor-pointer transition-all",
                                enableFallback ? "bg-primary/5 border-primary/40 text-primary shadow-sm" : "bg-black/5 dark:bg-black/20 border-border/20 text-secondary hover:border-border/50"
                            )}
                        >
                            <div className={cn("w-5 h-5 rounded-lg border flex items-center justify-center transition-all", enableFallback ? "bg-primary border-primary shadow-md shadow-primary/20" : "border-border/50")}>
                                {enableFallback && <div className="w-2 h-2 bg-white rounded-full shadow-sm" />}
                            </div>
                            <div className="flex-1">
                                <div className="text-sm font-bold">{t('opt_fallback')}</div>
                                <div className="text-xs opacity-60 font-medium">{t('opt_fallback_desc')}</div>
                            </div>
                        </div>
                    </div>

                    {/* Advanced Options Toggles */}
                    <div className="space-y-3 pt-4 border-t border-border/30">
                        <div className="flex gap-2">
                            <ToggleOption
                                active={useLocalNfo}
                                onClick={() => setUseLocalNfo(!useLocalNfo)}
                                icon={<FileText className="w-4 h-4" />}
                                label={t('opt_local_nfo')}
                            />
                            <ToggleOption
                                active={extraImages}
                                onClick={() => setExtraImages(!extraImages)}
                                icon={<FileImage className="w-4 h-4" />}
                                label={t('opt_extra_images')}
                            />
                        </div>
                    </div>

                    {/* Workers Slider */}
                    <div className="flex flex-col gap-2 pt-4 border-t border-border/30">
                        <label className="text-xs text-secondary font-medium uppercase tracking-wider pl-1 flex justify-between">
                            <span>{t('concurrency')}</span>
                            <span className="font-mono text-primary">{workers}</span>
                        </label>
                        <input
                            type="range"
                            min="1"
                            max="16"
                            step="1"
                            value={workers}
                            onChange={(e) => setWorkers(parseInt(e.target.value))}
                            className="w-full h-1 bg-white/20 rounded-lg appearance-none cursor-pointer accent-primary"
                        />
                    </div>

                    {/* Start Button */}
                    <button
                        disabled={isRunning || !selectedPath || (strategy === 'copy' && !outputPath)}
                        onClick={handleStart}
                        className="w-full py-4 bg-primary hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-xl font-bold flex items-center justify-center gap-2 transition-all shadow-[0_0_20px_rgba(var(--accent-primary),0.3)] hover:shadow-[0_0_30px_rgba(var(--accent-primary),0.5)] active:scale-[0.98] mt-4"
                    >
                        <Play className="w-5 h-5 fill-current" />
                        {t('start_task')}
                    </button>

                    {strategy === 'organize' && (
                        <div className="flex items-center gap-2 text-xs text-orange-400 justify-center">
                            <ShieldAlert className="w-3 h-3" />
                            {t('warning_inplace')}
                        </div>
                    )}
                </div>

                <FolderPicker className="flex-1 glass-panel rounded-xl overflow-hidden min-h-[300px]" onSelect={setSelectedPath} />
            </div>

            {/* Right: Terminal */}
            <div className="lg:col-span-2 h-full min-h-[500px]">
                <TerminalView className="h-full glass-panel rounded-xl border border-border/50 shadow-2xl" />
            </div>
        </div>
    );
}

function StrategyCard({ active, onClick, icon, title, desc, warn }: any) {
    return (
        <div
            onClick={onClick}
            className={cn(
                "flex items-start gap-3.5 p-4 rounded-xl cursor-pointer border transition-all duration-300",
                active
                    ? (warn ? "bg-orange-500/10 border-orange-500/50 shadow-sm" : "bg-primary/10 border-primary/50 shadow-sm")
                    : "bg-black/5 dark:bg-black/20 border-border/20 hover:bg-white/5 hover:border-border/50"
            )}
        >
            <div className={cn("mt-0.5", active ? (warn ? "text-orange-400" : "text-primary") : "text-secondary")}>
                {icon}
            </div>
            <div className="flex-1">
                <div className={cn("text-base font-bold leading-none", active ? "text-foreground" : "text-secondary")}>{title}</div>
                <div className="text-xs text-muted leading-relaxed mt-1.5 font-medium">{desc}</div>
            </div>
        </div>
    )
}

function ToggleOption({ active, onClick, icon, label }: any) {
    return (
        <div
            onClick={onClick}
            className={cn(
                "flex-1 flex flex-col items-center justify-center gap-2.5 p-4 rounded-xl border cursor-pointer transition-all duration-300",
                active ? "bg-primary/10 border-primary/40 text-primary shadow-sm" : "bg-black/5 dark:bg-black/20 border-border/20 text-secondary hover:bg-white/5"
            )}
        >
            <div className={active ? "scale-110 transition-transform" : ""}>{icon}</div>
            <span className="text-sm font-bold text-center leading-tight">{label}</span>
        </div>
    )
}
