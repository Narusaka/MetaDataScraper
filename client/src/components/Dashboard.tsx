import { useState, useEffect } from 'react';
import {
    Play, FolderInput, Copy,
    Search, FolderOpen, X, Settings2,
    Database, Layers, Cpu
} from 'lucide-react';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/language';
import { FolderPicker } from './FolderPicker';
import { TaskBoard } from './TaskBoard';
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
    const [workers] = useState(() => parseInt(localStorage.getItem('task_workers') || "4"));
    const [useLocalNfo, setUseLocalNfo] = useState(() => localStorage.getItem('task_local_nfo') === 'true');
    const [extraImages, setExtraImages] = useState(() => localStorage.getItem('task_extra_images') === 'true');
    const [outputPath, setOutputPath] = useState(() => localStorage.getItem('task_output_path') || "");
    const [mediaType, setMediaType] = useState(() => localStorage.getItem('task_media_type') || "");
    const [tmdbId, setTmdbId] = useState(() => localStorage.getItem('task_tmdb_id') || "");
    const [searchMode] = useState<'smart' | 'tmdb_only' | 'tavily_only'>(() => (localStorage.getItem('task_search_mode') as 'smart' | 'tmdb_only' | 'tavily_only') || 'smart');
    const [multiMode, setMultiMode] = useState<'auto' | 'single' | 'batch'>(() => (localStorage.getItem('task_multi_mode') as 'auto' | 'single' | 'batch') || 'auto');
    const [forceFresh, setForceFresh] = useState(false);

    // --- Persistence ---
    useEffect(() => {
        if (selectedPath) localStorage.setItem('last_path', selectedPath);
    }, [selectedPath]);
    useEffect(() => localStorage.setItem('task_strategy', strategy), [strategy]);
    // Workers persistence removed from setter but state kept for API
    useEffect(() => localStorage.setItem('task_local_nfo', useLocalNfo.toString()), [useLocalNfo]);
    useEffect(() => localStorage.setItem('task_extra_images', extraImages.toString()), [extraImages]);
    useEffect(() => localStorage.setItem('task_output_path', outputPath), [outputPath]);
    useEffect(() => localStorage.setItem('task_media_type', mediaType), [mediaType]);
    useEffect(() => localStorage.setItem('task_tmdb_id', tmdbId), [tmdbId]);
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

    return (
        <div className="flex flex-col h-full overflow-hidden font-sans gap-4">
            {/* Top Bar: Target Selection & Actions */}
            <div className="shrink-0 flex items-center justify-between gap-6 p-1">
                {/* Target Input */}
                <div className="flex-1 relative group">
                    <div className="flex items-center bg-bg-surface rounded-2xl overflow-hidden shadow-sm transition-all focus-within:ring-2 focus-within:ring-primary/20">
                        <div className="px-4 py-3 bg-bg-surface border-r border-border-light/20 flex items-center gap-2 text-primary font-bold text-xs uppercase tracking-wider">
                            <FolderOpen size={16} />
                            <span>{t('target_path')}</span>
                        </div>
                        <input
                            type="text"
                            value={selectedPath}
                            onChange={(e) => setSelectedPath(e.target.value)}
                            placeholder="/path/to/media/source"
                            className="flex-1 bg-transparent border-none text-sm text-text-main px-4 py-3 outline-none font-medium placeholder:text-text-muted/40"
                        />
                        <button
                            onClick={() => setShowPicker('input')}
                            className="px-4 py-3 text-text-muted hover:text-text-main transition-colors"
                        >
                            <FolderInput size={20} />
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
                        "relative flex items-center gap-3 px-8 py-3 rounded-2xl font-bold text-sm tracking-wide uppercase transition-all overflow-hidden shadow-lg shadow-primary/30",
                        isRunning
                            ? "bg-bg-surface text-text-muted cursor-not-allowed shadow-none"
                            : !selectedPath
                                ? "bg-bg-surface text-text-muted cursor-not-allowed shadow-none"
                                : "bg-primary text-white hover:brightness-110"
                    )}
                >
                    {/* Button Glow for Active State */}
                    {!isRunning && selectedPath && (
                        <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent translate-x-[-100%] animate-[shimmer_2s_infinite]" />
                    )}

                    {isRunning ? (
                        <div className="flex items-center gap-2">
                            <div className="w-4 h-4 border-2 border-white/50 border-t-white rounded-full animate-spin" />
                            <span>{t('running')}</span>
                        </div>
                    ) : (
                        <>
                            <Play size={16} fill="currentColor" />
                            <span>
                                {!selectedPath ? t('execute_protocol_disabled_path') : t('execute_protocol')}
                            </span>
                        </>
                    )}
                </motion.button>
            </div>

            {/* Main Content: Sidebar + TaskBoard */}
            <div className="flex-1 flex gap-6 overflow-hidden min-h-0">
                {/* Configuration Sidebar */}
                <div className="w-80 shrink-0 flex flex-col glass-panel-pro rounded-3xl border border-glass-border overflow-hidden shadow-xl">
                    <div className="p-4 border-b border-border-light/20 bg-bg-surface/50 backdrop-blur-md">
                        <div className="flex items-center gap-2 text-text-main font-bold">
                            <Settings2 size={16} className="text-primary" />
                            <span className="tracking-tight uppercase text-xs">{t('mission_configuration')}</span>
                        </div>
                    </div>

                    <div className="flex-1 overflow-y-auto p-5 scrollbar-thin space-y-6">

                        {/* Strategy Selector */}
                        <div className="space-y-3">
                            <SectionHeader icon={Layers} title={t('strategy')} />
                            <SegmentedControl
                                options={[
                                    { value: 'audit', label: t('mode_audit'), icon: Search },
                                    { value: 'organize', label: t('mode_organize'), icon: FolderInput },
                                    { value: 'copy', label: t('mode_copy'), icon: Copy },
                                ]}
                                value={strategy}
                                onChange={(v: any) => setStrategy(v as Strategy)}
                            />

                            <AnimatePresence>
                                {strategy === 'copy' && (
                                    <motion.div
                                        initial={{ opacity: 0, height: 0 }}
                                        animate={{ opacity: 1, height: 'auto' }}
                                        exit={{ opacity: 0, height: 0 }}
                                        className="overflow-hidden pt-2"
                                    >
                                        <div className="relative group flex items-center bg-bg-surface rounded-xl p-1">
                                            <input
                                                type="text"
                                                value={outputPath}
                                                onChange={(e) => setOutputPath(e.target.value)}
                                                className="w-full bg-transparent border-none text-xs text-text-main px-3 py-2 outline-none font-medium placeholder:text-text-muted/40"
                                                placeholder={t('output_placeholder')}
                                            />
                                            <button
                                                onClick={() => setShowPicker('output')}
                                                className="p-2 text-text-muted hover:text-primary transition-colors"
                                            >
                                                <FolderOpen size={16} />
                                            </button>
                                        </div>
                                    </motion.div>
                                )}
                            </AnimatePresence>
                        </div>

                        {/* Media Settings */}
                        <div className="space-y-3">
                            <SectionHeader icon={Database} title={t('media_settings')} />

                            <div className="space-y-4">
                                <div className="space-y-1.5">
                                    <label className="text-[10px] uppercase font-bold text-text-muted tracking-wider ml-1">{t('process_mode')}</label>
                                    <SegmentedControl
                                        options={[
                                            { value: '', label: t('auto') },
                                            { value: 'movie', label: t('movie') },
                                            { value: 'tv', label: t('tv') },
                                        ]}
                                        value={mediaType}
                                        onChange={setMediaType}
                                    />
                                </div>

                                <div className="space-y-1.5">
                                    <label className="text-[10px] uppercase font-bold text-text-muted tracking-wider ml-1">{t('concurrency')}</label>
                                    <SegmentedControl
                                        options={[
                                            { value: 'auto', label: t('auto') },
                                            { value: 'single', label: t('mode_single') },
                                            { value: 'batch', label: t('mode_batch') },
                                        ]}
                                        value={multiMode}
                                        onChange={(v: any) => setMultiMode(v as any)}
                                    />
                                </div>

                                <div className="space-y-1.5">
                                    <label className="text-[10px] uppercase font-bold text-text-muted tracking-wider ml-1 flex justify-between">
                                        <span>{t('tmdb_override')}</span>
                                        <span className="text-[9px] opacity-50">{t('optional')}</span>
                                    </label>
                                    <div className="bg-bg-surface rounded-xl px-3 py-2">
                                        <input
                                            type="number"
                                            value={tmdbId}
                                            onChange={(e) => setTmdbId(e.target.value)}
                                            className="w-full bg-transparent border-none text-xs text-text-main outline-none placeholder:text-text-muted/40 p-0"
                                            placeholder={t('tmdb_placeholder')}
                                        />
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Parameters */}
                        <div className="space-y-3">
                            <SectionHeader icon={Cpu} title={t('parameters')} />
                            <div className="bg-bg-surface rounded-xl p-3 space-y-1">
                                <Switch label={t('opt_local_nfo')} checked={useLocalNfo} onChange={setUseLocalNfo} />
                                <Switch label={t('opt_extra_images')} checked={extraImages} onChange={setExtraImages} />
                                <div className="h-px bg-border-light/10 my-1" />
                                <Switch label={t('force_refresh_danger')} checked={forceFresh} onChange={setForceFresh} danger />
                            </div>
                        </div>
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

function SectionHeader({ icon: Icon, title }: any) {
    return (
        <div className="flex items-center gap-2 mb-2 text-text-muted">
            <Icon size={14} className="text-primary/80" />
            <span className="text-[10px] font-bold uppercase tracking-[0.2em]">{title}</span>
            <div className="h-px flex-1 bg-gradient-to-r from-border-light to-transparent opacity-50" />
        </div>
    )
}

function SegmentedControl({ options, value, onChange }: any) {
    return (
        <div className="grid grid-cols-3 gap-1 p-1 bg-slate-200/50 dark:bg-black/40 rounded-lg border border-transparent dark:border-white/10 relative">
            {options.map((opt: any) => {
                const isActive = value === opt.value;
                return (
                    <button
                        key={opt.value}
                        onClick={() => onChange(opt.value)}
                        className={cn(
                            "relative z-10 flex flex-col items-center justify-center gap-1.5 py-2 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all",
                            isActive ? "text-[var(--text-on-active)]" : "text-text-muted hover:text-text-main"
                        )}
                    >
                        {isActive && (
                            <motion.div
                                layoutId={`segment-${options[0].value}`}
                                className="absolute inset-0 shadow-sm border border-border-light dark:border-primary/50 rounded-md bg-[var(--bg-panel)] dark:bg-[var(--primary)]"
                                initial={false}
                                transition={{ type: "spring", stiffness: 300, damping: 30 }}
                            />
                        )}
                        <span className="relative z-10 flex items-center gap-1.5">
                            {opt.icon && <opt.icon size={14} />}
                            {opt.label}
                        </span>
                    </button>
                )
            })}
        </div>
    )
}

function Switch({ checked, onChange, label, danger }: any) {
    return (
        <div className="flex items-center justify-between py-2.5 px-2">
            <span className="text-[11px] font-medium text-text-main/90">{label}</span>
            <button
                onClick={() => onChange(!checked)}
                className={cn(
                    "w-11 h-6 rounded-full transition-colors duration-300 relative focus:outline-none",
                    checked
                        ? (danger ? "bg-red-500" : "bg-[var(--ios-green)]") // Use new iOS green variable
                        : "bg-stone-300 dark:bg-stone-700"
                )}
            >
                <motion.div
                    className="absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow-sm"
                    animate={{ x: checked ? 20 : 0 }}
                    transition={{ type: "spring", stiffness: 500, damping: 30 }}
                />
            </button>
        </div>
    )
}
