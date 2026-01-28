import { useState, useEffect } from 'react';
import {
    Play, FolderInput, Copy,
    Search, FolderOpen, X, Settings2,
    Database, Layers, Cpu, Radio, ShieldCheck
} from 'lucide-react';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/language';
import { FolderPicker } from './FolderPicker';
import { TaskBoard } from './TaskBoard';
import { SystemMonitor } from './SystemMonitor';
import { motion, AnimatePresence } from 'framer-motion';

interface DashboardProps {
    isRunning: boolean;
    onStart: (config: any) => void;
}

type Strategy = 'audit' | 'organize' | 'copy';

export function Dashboard({ isRunning, onStart }: DashboardProps) {
    const { t } = useTranslation();

    // --- State Management ---
    const [selectedPath, setSelectedPath] = useState(() => localStorage.getItem('last_path') || "");
    const [showPicker, setShowPicker] = useState<'input' | 'output' | null>(null);

    const [strategy, setStrategy] = useState<Strategy>(() => (localStorage.getItem('task_strategy') as Strategy) || 'audit');
    const [workers, setWorkers] = useState(() => parseInt(localStorage.getItem('task_workers') || "4"));
    const [useLocalNfo, setUseLocalNfo] = useState(() => localStorage.getItem('task_local_nfo') === 'true');
    const [extraImages, setExtraImages] = useState(() => localStorage.getItem('task_extra_images') === 'true');
    const [outputPath, setOutputPath] = useState(() => localStorage.getItem('task_output_path') || "");
    const [mediaType, setMediaType] = useState(() => localStorage.getItem('task_media_type') || "");
    const [tmdbId, setTmdbId] = useState(() => localStorage.getItem('task_tmdb_id') || "");
    const [searchMode, setSearchMode] = useState<'smart' | 'tmdb_only' | 'tavily_only'>(() => (localStorage.getItem('task_search_mode') as 'smart' | 'tmdb_only' | 'tavily_only') || 'smart');
    const [multiMode, setMultiMode] = useState<'auto' | 'single' | 'batch'>(() => (localStorage.getItem('task_multi_mode') as 'auto' | 'single' | 'batch') || 'auto');
    const [forceFresh, setForceFresh] = useState(false);

    // --- Persistence ---
    useEffect(() => {
        if (selectedPath) localStorage.setItem('last_path', selectedPath);
    }, [selectedPath]);
    useEffect(() => localStorage.setItem('task_strategy', strategy), [strategy]);
    useEffect(() => localStorage.setItem('task_workers', workers.toString()), [workers]);
    useEffect(() => localStorage.setItem('task_local_nfo', useLocalNfo.toString()), [useLocalNfo]);
    useEffect(() => localStorage.setItem('task_extra_images', extraImages.toString()), [extraImages]);
    useEffect(() => localStorage.setItem('task_output_path', outputPath), [outputPath]);
    useEffect(() => localStorage.setItem('task_media_type', mediaType), [mediaType]);
    useEffect(() => localStorage.setItem('task_tmdb_id', tmdbId), [tmdbId]);
    useEffect(() => localStorage.setItem('task_search_mode', searchMode), [searchMode]);
    useEffect(() => localStorage.setItem('task_multi_mode', multiMode), [multiMode]);

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
            enable_fallback: true,
            multi_mode: multiMode === 'auto' ? null : (multiMode === 'batch'),
            fresh: forceFresh
        });
    };

    const ControlPanelSection = ({ title, icon: Icon, children }: any) => (
        <div className="mb-6">
            <div className="flex items-center gap-2 mb-3 text-text-muted/60">
                <Icon size={14} />
                <span className="text-[10px] font-bold uppercase tracking-[0.2em]">{title}</span>
                <div className="h-px flex-1 bg-gradient-to-r from-border-light to-transparent opacity-50" />
            </div>
            <div className="space-y-3">
                {children}
            </div>
        </div>
    );

    return (
        <div className="flex flex-col h-full overflow-hidden font-sans gap-4">
            {/* Top Bar: Target Selection & Actions */}
            <div className="shrink-0 flex items-center justify-between gap-6 p-1">
                {/* Target Input */}
                <div className="flex-1 relative group">
                    <div className="absolute inset-0 bg-primary/20 blur-xl rounded-lg opacity-0 group-focus-within:opacity-100 transition-opacity duration-500 pointer-events-none" />
                    <div className="flex items-center bg-panel border border-border-light rounded-xl overflow-hidden focus-within:border-primary/50 focus-within:ring-1 focus-within:ring-primary/20 transition-all shadow-sm">
                        <div className="px-4 py-3 bg-surface/50 border-r border-border-light flex items-center gap-2 text-primary font-mono text-xs font-bold uppercase tracking-wider">
                            <FolderOpen size={14} />
                            <span>Target</span>
                        </div>
                        <input
                            type="text"
                            value={selectedPath}
                            onChange={(e) => setSelectedPath(e.target.value)}
                            placeholder="/path/to/media/source"
                            className="flex-1 bg-transparent border-none text-sm text-text-main px-4 py-3 outline-none font-mono placeholder:text-text-muted/40"
                        />
                        <button
                            onClick={() => setShowPicker('input')}
                            className="px-4 py-3 text-text-muted hover:text-text-main hover:bg-white/5 transition-colors border-l border-border-light/50"
                        >
                            <FolderInput size={18} />
                        </button>
                    </div>
                </div>

                {/* Primary Action Button */}
                <motion.button
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.98 }}
                    onClick={handleStart}
                    disabled={isRunning || !selectedPath}
                    className={cn(
                        "relative flex items-center gap-3 px-8 py-3 rounded-xl font-bold text-sm tracking-wide uppercase transition-all overflow-hidden",
                        isRunning
                            ? "bg-surface border border-border-light text-text-muted cursor-not-allowed"
                            : "text-white dark:text-black shadow-lg shadow-primary/40 hover:shadow-primary/60 hover:brightness-110 border border-white/20"
                    )}
                    style={!isRunning ? { backgroundColor: 'var(--primary)' } : undefined}
                >
                    {/* Button Glow for Active State */}
                    {!isRunning && (
                        <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/30 to-transparent translate-x-[-100%] animate-[shimmer_2s_infinite]" />
                    )}

                    {isRunning ? (
                        <div className="flex items-center gap-2">
                            <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
                            <span>{t('running')}</span>
                        </div>
                    ) : (
                        <>
                            <Play size={16} fill="currentColor" />
                            <span>EXECUTE PROTOCOL</span>
                        </>
                    )}
                </motion.button>
            </div>

            {/* System Monitor Area */}
            <SystemMonitor />

            {/* Main Content: Sidebar + TaskBoard */}
            <div className="flex-1 flex gap-6 overflow-hidden min-h-0">
                {/* Configuration Sidebar */}
                <div className="w-80 shrink-0 flex flex-col glass-panel-pro rounded-2xl border border-glass-border overflow-hidden">
                    <div className="p-4 border-b border-border-light/50 bg-black/20 backdrop-blur-md">
                        <div className="flex items-center gap-2 text-text-main font-bold">
                            <Settings2 size={16} className="text-primary" />
                            <span className="tracking-tight uppercase text-xs">Mission Configuration</span>
                        </div>
                    </div>

                    <div className="flex-1 overflow-y-auto p-5 scrollbar-thin">
                        <ControlPanelSection title={t('strategy')} icon={Layers}>
                            <div className="grid grid-cols-3 gap-1 p-1 bg-black/20 rounded-lg border border-white/5">
                                {(['audit', 'organize', 'copy'] as const).map(s => (
                                    <button
                                        key={s}
                                        onClick={() => setStrategy(s)}
                                        className={cn(
                                            "flex flex-col items-center justify-center gap-1.5 py-2.5 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all",
                                            strategy === s
                                                ? "bg-primary text-white shadow-lg shadow-primary/25 ring-1 ring-white/10"
                                                : "text-text-muted hover:text-text-main hover:bg-white/5"
                                        )}
                                    >
                                        {s === 'audit' && <Search size={16} />}
                                        {s === 'organize' && <FolderInput size={16} />}
                                        {s === 'copy' && <Copy size={16} />}
                                        <span>{t(`mode_${s}` as any)}</span>
                                    </button>
                                ))}
                            </div>

                            <AnimatePresence>
                                {strategy === 'copy' && (
                                    <motion.div
                                        initial={{ opacity: 0, height: 0 }}
                                        animate={{ opacity: 1, height: 'auto' }}
                                        exit={{ opacity: 0, height: 0 }}
                                        className="mt-3 overflow-hidden"
                                    >
                                        <div className="relative group">
                                            <input
                                                type="text"
                                                value={outputPath}
                                                onChange={(e) => setOutputPath(e.target.value)}
                                                className="w-full bg-surface/50 border border-border-light rounded-lg px-3 py-2 text-xs text-text-mono font-mono focus:border-primary/50 outline-none pr-8"
                                                placeholder="/destination/path"
                                            />
                                            <button
                                                onClick={() => setShowPicker('output')}
                                                className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-primary transition-colors"
                                            >
                                                <FolderOpen size={14} />
                                            </button>
                                        </div>
                                    </motion.div>
                                )}
                            </AnimatePresence>
                        </ControlPanelSection>

                        <ControlPanelSection title={t('media_settings')} icon={Database}>
                            {/* Type */}
                            <div className="space-y-1">
                                <label className="text-[10px] text-text-muted font-bold block mb-1.5">Processing Mode</label>
                                <div className="flex gap-1 p-0.5 bg-black/20 rounded-lg border border-white/5">
                                    {['', 'movie', 'tv'].map(type => (
                                        <button
                                            key={type}
                                            onClick={() => setMediaType(type)}
                                            className={cn(
                                                "flex-1 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider transition-colors",
                                                mediaType === type
                                                    ? "bg-white/10 text-white shadow-sm border border-white/5"
                                                    : "text-text-muted hover:text-text-main hover:bg-white/5"
                                            )}
                                        >
                                            {type || 'Auto'}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            {/* Mode Selection */}
                            <div className="space-y-1 mt-4">
                                <label className="text-[10px] text-text-muted font-bold block mb-1.5">Concurrency Mode</label>
                                <div className="grid grid-cols-3 gap-1">
                                    {(['auto', 'single', 'batch'] as const).map(m => (
                                        <button
                                            key={m}
                                            onClick={() => setMultiMode(m)}
                                            className={cn(
                                                "py-1.5 rounded-md text-[9px] font-bold uppercase tracking-wider transition-all border",
                                                multiMode === m
                                                    ? "bg-primary/20 border-primary/30 text-primary-300"
                                                    : "bg-transparent border-border-light text-text-muted/60 hover:bg-white/5"
                                            )}
                                        >
                                            {m}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            {/* TMDB ID */}
                            <div className="mt-4">
                                <label className="text-[10px] text-text-muted font-bold block mb-1.5 flex items-center justify-between">
                                    <span>Override TMDB ID</span>
                                    <span className="text-[9px] text-text-muted/40 font-mono">OPTIONAL</span>
                                </label>
                                <input
                                    type="number"
                                    value={tmdbId}
                                    onChange={(e) => setTmdbId(e.target.value)}
                                    className="w-full bg-surface/50 border border-border-light rounded-lg px-3 py-2 text-xs font-mono text-text-main focus:border-primary/50 outline-none placholder:text-text-muted/20"
                                    placeholder="e.g. 550"
                                />
                            </div>
                        </ControlPanelSection>

                        <ControlPanelSection title="PARAMETERS" icon={Cpu}>
                            <div className="space-y-2">
                                <ToggleRow active={useLocalNfo} onClick={() => setUseLocalNfo(!useLocalNfo)} label={t('opt_local_nfo')} />
                                <ToggleRow active={extraImages} onClick={() => setExtraImages(!extraImages)} label={t('opt_extra_images')} />
                                <div className="pt-2 border-t border-white/5">
                                    <ToggleRow active={forceFresh} onClick={() => setForceFresh(!forceFresh)} label="Force Refresh (Danger)" danger />
                                </div>
                            </div>

                            {/* Threads */}
                            <div className="pt-4">
                                <div className="flex justify-between items-center mb-2">
                                    <span className="text-[10px] font-bold text-text-muted uppercase">Thread Allocation</span>
                                    <span className="text-xs font-mono text-primary">{workers} CORES</span>
                                </div>
                                <input
                                    type="range" min="1" max="16"
                                    value={workers}
                                    onChange={(e) => setWorkers(parseInt(e.target.value))}
                                    className="w-full accent-primary h-1 bg-surface rounded-full appearance-none cursor-pointer"
                                />
                            </div>
                        </ControlPanelSection>
                    </div>
                </div>

                {/* Task Board */}
                <div className="flex-1 rounded-2xl overflow-hidden relative glass-panel-pro border border-glass-border flex flex-col">
                    <TaskBoard defaultConfig={{ strategy, outputPath, forceFresh }} />
                </div>
            </div>

            {/* Folder Picker Modal */}
            <AnimatePresence>
                {showPicker && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-8"
                        onClick={() => setShowPicker(null)}
                    >
                        <motion.div
                            initial={{ scale: 0.9, y: 20 }}
                            animate={{ scale: 1, y: 0 }}
                            exit={{ scale: 0.9, y: 20 }}
                            className="w-full max-w-3xl glass-panel-pro rounded-2xl shadow-2xl flex flex-col max-h-[80vh] overflow-hidden"
                            onClick={e => e.stopPropagation()}
                        >
                            <div className="h-14 border-b border-white/10 flex items-center px-6 justify-between bg-white/5">
                                <span className="text-sm font-bold text-text-main uppercase tracking-widest font-display">{t('modal_title')}</span>
                                <button onClick={() => setShowPicker(null)} className="text-text-muted hover:text-white transition-colors"><X size={20} /></button>
                            </div>
                            <div className="flex-1 overflow-auto p-4 bg-black/40">
                                <FolderPicker
                                    initialPath={showPicker === 'input' ? selectedPath : outputPath}
                                    onSelect={(path) => {
                                        if (showPicker === 'input') setSelectedPath(path);
                                        else setOutputPath(path);
                                    }}
                                />
                            </div>
                            <div className="p-4 border-t border-white/10 bg-white/5 flex justify-end">
                                <button onClick={() => setShowPicker(null)} className="px-8 py-2.5 bg-primary hover:bg-primary-hover text-white font-bold text-xs uppercase rounded-lg shadow-lg shadow-primary/20 transition-all hover:scale-[1.02] active:scale-95">
                                    {t('confirm_selection')}
                                </button>
                            </div>
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}

function ToggleRow({ active, onClick, label, danger }: { active: boolean, onClick: () => void, label: string, danger?: boolean }) {
    return (
        <button
            onClick={onClick}
            className={cn(
                "w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs transition-all border hover:border-white/10",
                active
                    ? (danger
                        ? "bg-red-500/10 border-red-500/20 text-red-400"
                        : "bg-primary/10 border-primary/20 text-text-main shadow-[0_0_15px_-5px_var(--primary)]")
                    : "bg-transparent border-transparent text-text-muted hover:bg-white/5"
            )}
        >
            <span className="font-medium tracking-wide">{label}</span>
            <div className={cn(
                "w-2.5 h-2.5 rounded-full transition-all shadow-sm",
                active
                    ? (danger ? "bg-red-500 shadow-[0_0_8px_var(--accent-error)]" : "bg-primary shadow-[0_0_8px_var(--primary)]")
                    : "bg-surface border border-text-muted/30"
            )} />
        </button>
    )
}
