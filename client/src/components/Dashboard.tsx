import { useState, useEffect, useRef } from 'react';
import {
    Play, FolderInput, Copy,
    Search, FolderOpen, X, Settings2,
    Database, Layers, Cpu, Square, FileText, Image, FolderCog,
    type LucideIcon
} from 'lucide-react';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/languageContext';
import { FolderPicker } from './FolderPicker';
import { TaskBoard } from './TaskBoard';
import { apiJson } from '../lib/api';
import {
    validateStartSafetyConfig,
    type StartSafetyConfig,
} from '../lib/taskStartSafety';
import type { FileSystemCheckResponse, TaskStartPayload } from '../lib/types';
import { toast } from 'sonner';
import { motion, AnimatePresence } from 'framer-motion';

interface DashboardProps {
    isRunning: boolean;
    onPlan: (config: TaskStartPayload) => void;
    onStop: () => void;
}

type Strategy = 'audit' | 'organize' | 'copy';
type ConflictStrategy = 'error' | 'skip' | 'suffix' | 'overwrite';
type OperationScope = 'full' | 'nfo_only' | 'artwork_only' | 'organize_only';

export function Dashboard({ isRunning, onPlan, onStop }: DashboardProps) {
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
    // Fixed: searchMode removed to prevent being stuck in tavily_only from stale localStorage
    // Re-introducing searchMode but with default 'smart' if localStorage value is invalid, and exposing it to UI
    const [searchMode, setSearchMode] = useState<'smart' | 'tmdb_only' | 'tavily_only'>(() => {
        const stored = localStorage.getItem('task_search_mode');
        // Validate stored value
        if (stored === 'smart' || stored === 'tmdb_only' || stored === 'tavily_only') return stored;
        return 'smart';
    });
    const [multiMode, setMultiMode] = useState<'auto' | 'single' | 'batch'>(() => (localStorage.getItem('task_multi_mode') as 'auto' | 'single' | 'batch') || 'auto');
    const [forceFresh, setForceFresh] = useState(false);
    const [overwriteImages, setOverwriteImages] = useState(() => localStorage.getItem('task_overwrite_images') === 'true');
    const [renameParentDir, setRenameParentDir] = useState(() => localStorage.getItem('task_rename_parent') === 'true');
    const [conflictStrategy, setConflictStrategy] = useState<ConflictStrategy>(() => {
        const stored = localStorage.getItem('task_conflict_strategy');
        return stored === 'skip' || stored === 'suffix' || stored === 'overwrite' ? stored : 'error';
    });
    const [operationScope, setOperationScope] = useState<OperationScope>(() => {
        const stored = localStorage.getItem('task_operation_scope');
        return stored === 'nfo_only' || stored === 'artwork_only' || stored === 'organize_only' ? stored : 'full';
    });
    const [isScrolling, setIsScrolling] = useState(false);
    const scrollTimer = useRef<number | null>(null);

    const handleScroll = () => {
        setIsScrolling(true);
        if (scrollTimer.current) window.clearTimeout(scrollTimer.current);
        scrollTimer.current = window.setTimeout(() => {
            setIsScrolling(false);
        }, 2000);
    };

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
    useEffect(() => localStorage.setItem('task_overwrite_images', overwriteImages.toString()), [overwriteImages]);
    useEffect(() => localStorage.setItem('task_rename_parent', renameParentDir.toString()), [renameParentDir]);
    useEffect(() => localStorage.setItem('task_conflict_strategy', conflictStrategy), [conflictStrategy]);
    useEffect(() => localStorage.setItem('task_operation_scope', operationScope), [operationScope]);

    const normalizedInputPath = selectedPath.trim();
    const normalizedOutputPath = outputPath.trim();
    const effectiveWorkers = Math.min(16, Math.max(1, Number.isFinite(workers) ? workers : 1));
    const scopeAllowsOrganize = operationScope === 'full' || operationScope === 'organize_only';
    const scopeAllowsArtwork = operationScope === 'full' || operationScope === 'artwork_only';
    const effectiveEnableOrganize = scopeAllowsOrganize && strategy !== 'audit';
    const effectiveExtraImages = scopeAllowsArtwork && extraImages;
    const effectiveOverwriteImages = scopeAllowsArtwork && overwriteImages;
    const effectiveRenameParentDir = scopeAllowsOrganize && strategy !== 'audit' && renameParentDir;
    const startSafetyConfig: StartSafetyConfig = {
        strategy,
        inputPath: normalizedInputPath,
        outputPath: normalizedOutputPath,
        extraImages: effectiveExtraImages,
        overwriteImages: effectiveOverwriteImages,
        renameParentDir: effectiveRenameParentDir,
        forceFresh,
        enableOrganize: effectiveEnableOrganize,
        workers: effectiveWorkers,
        searchMode,
        conflictStrategy,
        operationScope,
    };

    const validateStartConfig = () => {
        const safetyError = validateStartSafetyConfig(startSafetyConfig);
        if (safetyError) return safetyError;
        if (multiMode === 'single' && tmdbId && Number.isNaN(parseInt(tmdbId))) return 'TMDB ID must be numeric';
        return null;
    };

    const handleStart = async () => {
        if (isRunning) {
            onStop();
            return false;
        }

        const validationError = validateStartConfig();
        if (validationError) {
            toast.error(validationError);
            return false;
        }

        const toastId = toast.loading('Generating locked plan...');

        try {
            await onPlan({
                input_dir: normalizedInputPath,
                workers: effectiveWorkers,
                dry_run: true,
                inplace: strategy === 'organize',
                copy_mode: strategy === 'copy',
                output_dir: strategy === 'copy' ? normalizedOutputPath : null,
                use_local_nfo: useLocalNfo,
                extra_images: effectiveExtraImages,
                media_type: mediaType || null,
                tmdb_id: (multiMode === 'single' && tmdbId) ? parseInt(tmdbId) : null,
                search_mode: searchMode,
                enable_fallback: true,
                multi_mode: multiMode === 'auto' ? null : (multiMode === 'batch'),
                fresh: forceFresh,
                enable_organize: effectiveEnableOrganize,
                overwrite_images: effectiveOverwriteImages,
                rename_parent_dir: effectiveRenameParentDir,
                conflict_strategy: conflictStrategy,
                operation_scope: operationScope,
                intended_strategy: strategy,
            });
            toast.success('Planning started. Review the result before execution.', { id: toastId });
            return true;
        } catch (e) {
            toast.error(`Failed to start task: ${e instanceof Error ? e.message : String(e)}`, { id: toastId });
            return false;
        }
    };

    return (
        <div className="flex min-h-full flex-col gap-4 overflow-visible pb-1 font-sans md:h-full md:min-h-0 md:overflow-hidden">
            {/* Top Bar: Target Selection & Actions (Floating Island) */}
            <div className="shrink-0 glass-panel-pro rounded-2xl md:rounded-3xl border border-glass-border shadow-sm px-4 md:px-6 py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3 md:gap-6 text-sm">
                {/* Target Selection Group */}
                <div className="flex min-w-0 flex-1 items-center gap-3 md:gap-4">
                    {/* Fixed Label Outside */}
                    <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-text-muted whitespace-nowrap">
                        {t('target_path')}
                    </span>

                    {/* Target Input */}
                    <div className="min-w-0 flex-1 relative group">
                        <div className="flex items-center bg-[var(--bg-input-target)] rounded-2xl overflow-hidden transition-all focus-within:ring-2 focus-within:ring-primary/20 p-1">
                            <input
                                type="text"
                                id="target-path-input"
                                value={selectedPath}
                                onChange={(e) => setSelectedPath(e.target.value)}
                                placeholder="/path/to/media/source"
                                className="min-w-0 flex-1 bg-transparent border-none text-sm text-text-main px-3 md:px-4 py-1.5 outline-none font-medium placeholder:text-text-muted/30"
                            />
                            <button
                                onClick={() => setShowPicker('input')}
                                className="w-8 h-8 rounded-full bg-[var(--bg-toggle-pill)] flex items-center justify-center text-text-muted hover:text-primary transition-all hover:scale-105 shadow-sm"
                            >
                                <FolderInput size={16} />
                            </button>
                        </div>
                    </div>
                </div>

                {/* Primary Action Button */}
                <motion.button
                    data-testid="dashboard-run-button"
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.98 }}
                    onClick={async () => {
                        if (isRunning) {
                            onStop();
                            return;
                        }

                        const validationError = validateStartConfig();
                        if (validationError) {
                            toast.error(validationError);
                            return;
                        }
                        try {
                            const checkData = await apiJson<FileSystemCheckResponse>(
                                `/api/fs/check?path=${encodeURIComponent(normalizedInputPath)}`,
                                undefined,
                                'Path check failed',
                            );
                            if (!checkData.exists) {
                                toast.error(`${t('path_not_found') || 'Path not found'}: ${normalizedInputPath}`, {
                                    position: 'top-center'
                                });
                                return;
                            }
                            if (!checkData.is_dir) {
                                toast.error(`Path is not a directory: ${checkData.path || normalizedInputPath}`, {
                                    position: 'top-center'
                                });
                                return;
                            }
                        } catch (e) {
                            console.error("Path check failed", e);
                            toast.error(e instanceof Error ? e.message : 'Path check failed');
                            return;
                        }
                        await handleStart();
                    }}
                    disabled={!normalizedInputPath && !isRunning}
                    className={cn(
                        "relative flex w-full sm:w-auto items-center justify-center gap-3 px-8 py-2.5 rounded-xl font-bold text-sm tracking-wide uppercase transition-all overflow-hidden shadow-lg sm:min-w-[140px]",
                        isRunning
                            ? "bg-red-500 text-white shadow-red-500/20 hover:bg-red-600"
                            : !normalizedInputPath
                                ? "bg-bg-surface text-text-muted cursor-not-allowed shadow-none"
                                : "bg-yellow-400 text-black hover:bg-yellow-300 shadow-yellow-400/20"
                    )}
                >
                    {/* Button Glow for Active State */}
                    {!isRunning && normalizedInputPath && (
                        <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent translate-x-[-100%] animate-[shimmer_2s_infinite]" />
                    )}

                    <div className="flex items-center gap-2">
                        {isRunning ? (
                            <>
                                <Square size={16} fill="currentColor" />
                                <span>STOP</span>
                            </>
                        ) : (
                            <>
                                <Play size={16} fill="currentColor" />
                                <span>PLAN</span>
                            </>
                        )}
                    </div>
                </motion.button>
            </div>

            {/* Main Content: Sidebar + TaskBoard */}
            <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-visible md:flex-row md:gap-6 md:overflow-hidden">
                {/* Configuration Sidebar - Already Floating Island */}
                <div className="flex w-full shrink-0 flex-col overflow-hidden rounded-2xl border border-glass-border glass-panel-pro shadow-xl md:w-80 md:rounded-3xl">
                    <div className="px-6 py-4 flex items-center justify-between shrink-0">
                        <div className="flex items-center gap-2 text-text-main font-bold">
                            <Settings2 size={16} className="text-primary" />
                            <span className="tracking-widest uppercase text-xs font-bold font-display opacity-80">{t('mission_configuration')}</span>
                        </div>
                    </div>

                    <div className="flex-1 overflow-visible px-4 pb-4 md:overflow-hidden">
                        <div
                            onScroll={handleScroll}
                            className={cn(
                                "bg-[var(--bg-inner-panel)] rounded-2xl p-4 h-auto overflow-visible scrollbar-thin space-y-6 md:h-full md:overflow-y-auto",
                                isScrolling && "scrollbar-active"
                            )}
                        >

                            {/* Strategy Selector */}
                            <div className="space-y-3">
                                <SectionHeader icon={Layers} title={t('strategy')} />
                                <SegmentedControl
                                    options={[
                                        { value: 'audit', label: 'Metadata', icon: Search },
                                        { value: 'organize', label: t('mode_organize'), icon: FolderInput },
                                        { value: 'copy', label: t('mode_copy'), icon: Copy },
                                    ]}
                                    value={strategy}
                                    onChange={setStrategy}
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

                                    {/* Search Mode */}
                                    <div className="space-y-1.5">
                                        <label className="text-[10px] uppercase font-bold text-text-muted tracking-wider ml-1">搜索模式 / Search Mode</label>
                                        <SegmentedControl
                                            options={[
                                                { value: 'smart', label: t('smart') || 'Smart' },
                                                { value: 'tmdb_only', label: 'TMDB' },
                                                { value: 'tavily_only', label: 'Tavily' },
                                            ]}
                                            value={searchMode}
                                            onChange={setSearchMode}
                                        />
                                    </div>

                                    {/* Concurrency */}
                                    <div className="space-y-1.5">
                                        <label className="text-[10px] uppercase font-bold text-text-muted tracking-wider ml-1">{t('concurrency')}</label>
                                        <SegmentedControl
                                            options={[
                                                { value: 'auto', label: t('auto') },
                                                { value: 'single', label: t('mode_single') },
                                                { value: 'batch', label: t('mode_batch') },
                                            ]}
                                            value={multiMode}
                                            onChange={setMultiMode}
                                        />
                                    </div>

                                    {/* Threads */}
                                    <div className="space-y-1.5">
                                        <label className="text-[10px] uppercase font-bold text-text-muted tracking-wider ml-1">Threads (Workers)</label>
                                        <div className="flex items-center gap-2 bg-bg-surface rounded-xl px-3 py-2">
                                            <Cpu size={14} className="text-text-muted" />
                                            <input
                                                type="number"
                                                min="1"
                                                max="16"
                                                value={workers}
                                                onChange={(e) => setWorkers(Math.min(16, Math.max(1, parseInt(e.target.value) || 1)))}
                                                className="w-full bg-transparent border-none text-xs text-text-main outline-none font-mono"
                                            />
                                        </div>
                                    </div>

                                    {/* TMDB Override - ONly shown in single mode */}
                                    <AnimatePresence>
                                        {multiMode === 'single' && (
                                            <motion.div
                                                initial={{ opacity: 0, height: 0 }}
                                                animate={{ opacity: 1, height: 'auto' }}
                                                exit={{ opacity: 0, height: 0 }}
                                                className="space-y-1.5 overflow-hidden"
                                            >
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
                                            </motion.div>
                                        )}
                                    </AnimatePresence>
                                </div>
                            </div>

                            {/* Parameters */}
                            <div className="space-y-3">
                                <SectionHeader icon={Cpu} title={t('parameters')} />
                                <div className="bg-bg-surface rounded-xl p-3 space-y-1">
                                    <div className="grid grid-cols-4 gap-1 pb-2">
                                        {([
                                            ['full', Layers, 'Full'],
                                            ['nfo_only', FileText, 'NFO'],
                                            ['artwork_only', Image, 'Art'],
                                            ['organize_only', FolderCog, 'Files'],
                                        ] as const).map(([value, Icon, label]) => (
                                            <button
                                                key={value}
                                                type="button"
                                                title={label}
                                                onClick={() => setOperationScope(value)}
                                                className={cn(
                                                    "flex h-9 items-center justify-center gap-1 rounded-lg border text-[9px] font-bold uppercase transition-colors",
                                                    operationScope === value
                                                        ? "border-primary/40 bg-primary/10 text-primary"
                                                        : "border-border-light text-text-muted hover:text-text-main"
                                                )}
                                            >
                                                <Icon size={12} />
                                                <span>{label}</span>
                                            </button>
                                        ))}
                                    </div>
                                    <Switch label={t('opt_local_nfo')} checked={useLocalNfo} onChange={setUseLocalNfo} />
                                    <Switch label={t('opt_extra_images')} checked={extraImages} onChange={setExtraImages} disabled={operationScope === 'nfo_only' || operationScope === 'organize_only'} />
                                    <Switch label={t('opt_overwrite_images')} checked={overwriteImages} onChange={setOverwriteImages} disabled={operationScope === 'nfo_only' || operationScope === 'organize_only'} />
                                    <Switch label={t('opt_rename_parent')} checked={renameParentDir} onChange={setRenameParentDir} disabled={!scopeAllowsOrganize || strategy === 'audit'} />
                                    <div className="space-y-1.5 px-1 pt-2">
                                        <label className="text-[10px] uppercase font-bold text-text-muted tracking-wider">目标冲突 / Conflicts</label>
                                        <select
                                            value={conflictStrategy}
                                            onChange={(event) => setConflictStrategy(event.target.value as ConflictStrategy)}
                                            className="h-9 w-full rounded-lg border border-border-light bg-bg-surface px-3 text-xs font-medium text-text-main outline-none focus:border-primary"
                                        >
                                            <option value="error">阻止并人工处理</option>
                                            <option value="skip">跳过已有目标</option>
                                            <option value="suffix">自动添加序号</option>
                                            <option value="overwrite">覆盖并创建备份</option>
                                        </select>
                                    </div>
                                    <div className="h-px bg-border-light/10 my-1" />
                                    <Switch label={t('force_refresh_danger')} checked={forceFresh} onChange={setForceFresh} danger />
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Task Board */}
                <div className="relative flex min-h-[70vh] flex-1 flex-col overflow-hidden rounded-2xl border border-glass-border glass-panel-pro shadow-xl md:min-h-0 md:rounded-3xl">
                    <TaskBoard defaultConfig={{
                        strategy,
                        outputPath: normalizedOutputPath,
                        searchMode,
                        forceFresh,
                        extraImages: effectiveExtraImages,
                        enableOrganize: effectiveEnableOrganize,
                        overwriteImages: effectiveOverwriteImages,
                        renameParentDir: effectiveRenameParentDir,
                        conflictStrategy,
                        operationScope,
                    }} />
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
                            className="w-full max-w-3xl glass-panel-pro rounded-3xl border border-glass-border shadow-2xl flex flex-col max-h-[80vh] overflow-hidden"
                            onClick={e => e.stopPropagation()}
                        >
                            <div className="h-16 border-b border-white/10 flex items-center px-8 justify-between bg-white/5 backdrop-blur-md">
                                <span className="text-sm font-bold text-text-main uppercase tracking-widest font-display">{t('modal_title')}</span>
                                <button onClick={() => setShowPicker(null)} className="w-8 h-8 rounded-full bg-black/20 flex items-center justify-center text-text-muted hover:text-white transition-colors hover:bg-red-500 hover:rotate-90"><X size={18} /></button>
                            </div>
                            <div className="flex-1 overflow-auto p-6 bg-black/20 dark:bg-black/40">
                                <FolderPicker
                                    initialPath={showPicker === 'input' ? selectedPath : outputPath}
                                    onSelect={(path) => {
                                        if (showPicker === 'input') setSelectedPath(path);
                                        else setOutputPath(path);
                                    }}
                                />
                            </div>
                            <div className="p-6 border-t border-white/10 bg-white/5 backdrop-blur-md flex justify-end">
                                <button onClick={() => setShowPicker(null)} className="px-8 py-2.5 bg-primary hover:bg-primary-hover text-white font-bold text-xs uppercase rounded-xl shadow-lg shadow-primary/20 transition-all hover:scale-[1.02] active:scale-95">
                                    {t('confirm_selection')}
                                </button>
                            </div>
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div >
    );
}

interface SectionHeaderProps {
    icon: LucideIcon;
    title: string;
}

function SectionHeader({ icon: Icon, title }: SectionHeaderProps) {
    return (
        <div className="flex items-center gap-2 mb-2 text-text-muted">
            <Icon size={14} className="text-primary/80" />
            <span className="text-[10px] font-bold uppercase tracking-[0.2em]">{title}</span>
            <div className="h-px flex-1 bg-gradient-to-r from-border-light to-transparent opacity-50" />
        </div>
    )
}

interface SegmentOption<T extends string> {
    value: T;
    label: string;
    icon?: LucideIcon;
}

interface SegmentedControlProps<T extends string> {
    options: Array<SegmentOption<T>>;
    value: T;
    onChange: (value: T) => void;
}

function SegmentedControl<T extends string>({ options, value, onChange }: SegmentedControlProps<T>) {
    return (
        <div className="grid grid-cols-3 gap-1 p-1 bg-[var(--bg-toggle-wrapper)] rounded-lg border border-transparent dark:border-white/10 relative">
            {options.map((opt) => {
                const isActive = value === opt.value;
                return (
                    <button
                        key={opt.value}
                        onClick={() => onChange(opt.value)}
                        className={cn(
                            "relative z-10 flex flex-col items-center justify-center gap-1.5 py-2 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all",
                            isActive ? "text-white" : "text-text-muted hover:text-text-main"
                        )}
                    >
                        {isActive && (
                            <motion.div
                                layoutId={`segment-${options[0].value}`}
                                className="absolute inset-0 rounded-md border border-[var(--primary)] bg-[var(--primary)] shadow-sm"
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

interface SwitchProps {
    checked: boolean;
    onChange: (checked: boolean) => void;
    label: string;
    danger?: boolean;
    disabled?: boolean;
}

function Switch({ checked, onChange, label, danger, disabled }: SwitchProps) {
    return (
        <div className={cn("flex items-center justify-between py-2.5 px-2", disabled && "opacity-60")}>
            <span className="text-[11px] font-medium text-text-main/90">{label}</span>
            <button
                onClick={() => !disabled && onChange(!checked)}
                disabled={disabled}
                className={cn(
                    "w-11 h-6 rounded-full transition-colors duration-300 relative focus:outline-none",
                    disabled && "cursor-not-allowed",
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
