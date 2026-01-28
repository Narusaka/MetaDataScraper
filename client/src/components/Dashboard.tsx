
import { useState, useEffect, useRef } from 'react';
import {
    Play, FolderInput, Copy,
    FileImage, FileText, Search, Settings2, Database,
    X, AlertCircle, FolderOpen
} from 'lucide-react';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/language';
import { FolderPicker } from './FolderPicker';
import { TaskBoard } from './TaskBoard';

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

    // Layout State
    const [sidebarWidth, setSidebarWidth] = useState(() => parseInt(localStorage.getItem('sidebar_width') || '350'));
    const isResizingRef = useRef(false);

    // --- Resizing Logic ---
    useEffect(() => {
        const handleMouseMove = (e: MouseEvent) => {
            if (!isResizingRef.current) return;
            const newWidth = Math.min(Math.max(e.clientX - 24, 280), 600); // 24 is padding/margin approx
            setSidebarWidth(newWidth);
        };
        const handleMouseUp = () => {
            if (isResizingRef.current) {
                isResizingRef.current = false;
                localStorage.setItem('sidebar_width', sidebarWidth.toString());
                document.body.style.cursor = 'default';
                document.body.style.userSelect = 'auto';
            }
        };
        window.addEventListener('mousemove', handleMouseMove);
        window.addEventListener('mouseup', handleMouseUp);
        return () => {
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
        };
    }, [sidebarWidth]);

    const startResizing = () => {
        isResizingRef.current = true;
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
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

    const handleStart = () => {
        // Save to Recent Paths
        if (selectedPath) {
            const history = JSON.parse(localStorage.getItem('recent_paths') || '[]');
            const newHistory = [selectedPath, ...history.filter((p: string) => p !== selectedPath)].slice(0, 5);
            localStorage.setItem('recent_paths', JSON.stringify(newHistory));
        }

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
            fresh: forceFresh // Pass the fresh param
        });
    };

    return (
        <div className="flex flex-col h-full gap-6">
            {/* Top Bar: Target Path Selection */}
            <div className="glass-panel rounded-2xl p-4 flex flex-col md:flex-row items-center gap-4 border border-white/10 shadow-xl">
                <div className="flex-1 min-w-0 w-full">
                    <label className="text-[10px] font-bold text-primary uppercase tracking-[0.2em] mb-1.5 block px-1">
                        {t('path_input')}
                    </label>
                    <div
                        onClick={() => setShowPicker('input')}
                        className="group flex items-center gap-3 bg-muted/50 hover:bg-muted/80 border border-border hover:border-primary/50 transition-all cursor-pointer rounded-xl px-4 py-3 min-h-[52px]"
                    >
                        <FolderInput className="w-5 h-5 text-primary/70 group-hover:text-primary shrink-0" />
                        <span className={cn(
                            "flex-1 truncate font-mono text-sm tracking-tight",
                            selectedPath ? "text-foreground" : "text-muted-foreground italic"
                        )}>
                            {selectedPath || t('select_folder')}
                        </span>
                        <Search className="w-4 h-4 text-muted-foreground group-hover:text-primary transition-colors" />
                    </div>
                </div>

                <div className="w-full md:w-auto h-full pt-5">
                    <button
                        disabled={isRunning || !selectedPath || (strategy === 'copy' && !outputPath)}
                        onClick={handleStart}
                        className={cn(
                            "h-[52px] px-8 rounded-xl font-bold flex items-center justify-center gap-2 transition-all transition-transform active:scale-95 shadow-lg",
                            isRunning
                                ? "bg-slate-700 text-slate-400 cursor-not-allowed"
                                : "bg-gradient-to-r from-blue-600 to-indigo-600 text-white hover:shadow-blue-500/25 hover:from-blue-500 hover:to-indigo-500 shadow-blue-500/20"
                        )}
                    >
                        {isRunning ? (
                            <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        ) : (
                            <Play className="w-5 h-5 fill-current" />
                        )}
                        <span className="uppercase tracking-widest text-sm">{isRunning ? t('running') : t('start_task')}</span>
                    </button>
                </div>
            </div>

            {/* Main Flex Layout */}
            <div className="flex-1 min-h-0 flex gap-0 pb-4 relative">

                {/* Left: Configuration Panel (Resizable) */}
                <div
                    style={{ width: sidebarWidth }}
                    className="flex flex-col gap-6 overflow-y-auto pr-3 scrollbar-thin shrink-0"
                >

                    {/* Strategy Section (Redesigned) */}
                    <div className="glass-panel p-4 rounded-2xl space-y-4">
                        <SectionHeader icon={<Database className="w-4 h-4" />} title={t('strategy')} />

                        {/* Compact Grid Selector */}
                        <div className="grid grid-cols-3 gap-2">
                            {[
                                { id: 'audit', icon: Search, label: t('mode_audit'), color: 'text-white' },
                                { id: 'organize', icon: FolderInput, label: t('mode_organize'), color: 'text-orange-400' },
                                { id: 'copy', icon: Copy, label: t('mode_copy'), color: 'text-blue-400' }
                            ].map((item) => {
                                const isActive = strategy === item.id;
                                const Icon = item.icon;
                                return (
                                    <button
                                        key={item.id}
                                        onClick={() => setStrategy(item.id as any)}
                                        className={cn(
                                            "flex flex-col items-center justify-center gap-2 py-3 rounded-xl border transition-all relative overflow-hidden",
                                            isActive
                                                ? "bg-white/10 border-white/20 shadow-lg scale-[1.02]"
                                                : "bg-black/20 border-white/5 hover:bg-white/5 hover:border-white/10"
                                        )}
                                    >
                                        <Icon className={cn("w-5 h-5", isActive ? item.color : "text-white/40")} />
                                        <span className={cn("text-[9px] font-bold uppercase tracking-wider", isActive ? "text-white" : "text-white/40")}>
                                            {item.label.split(' ')[0]} {/* Simplified Label */}
                                        </span>
                                        {isActive && <div className={cn("absolute inset-x-0 bottom-0 h-0.5",
                                            item.id === 'organize' ? "bg-orange-500" : item.id === 'copy' ? "bg-blue-500" : "bg-white/50"
                                        )} />}
                                    </button>
                                )
                            })}
                        </div>

                        {/* Description Box */}
                        <div className="bg-black/20 rounded-lg p-3 border border-white/5 min-h-[60px] flex items-center">
                            <p className="text-xs text-muted-foreground leading-relaxed">
                                {strategy === 'audit' && t('mode_audit_desc')}
                                {strategy === 'organize' && t('mode_organize_desc')}
                                {strategy === 'copy' && t('mode_copy_desc')}
                            </p>
                        </div>

                        {/* Output Path (Nested inside Strategy) */}
                        {strategy === 'copy' && (
                            <div className="pt-2 animate-in slide-in-from-top-1 fade-in">
                                <label className="text-[9px] font-bold text-blue-400 uppercase tracking-widest mb-2 block flex items-center gap-2">
                                    <div className="w-1 h-4 bg-blue-500 rounded-full" />
                                    {t('path_output' as any) || "Destination"}
                                </label>
                                <div
                                    onClick={() => setShowPicker('output')}
                                    className="group flex items-center gap-3 bg-blue-500/5 hover:bg-blue-500/10 border border-blue-500/20 hover:border-blue-500/40 p-3 rounded-xl cursor-pointer transition-all"
                                >
                                    <FolderInput className="w-4 h-4 text-blue-400 group-hover:scale-110 transition-transform" />
                                    <span className={cn("flex-1 text-xs font-mono truncate", outputPath ? "text-blue-100" : "text-blue-500/40 italic")}>
                                        {outputPath || t('select_folder')}
                                    </span>
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Media Filtering & Specific ID */}
                    <div className="glass-panel rounded-2xl p-5 space-y-6">
                        <SectionHeader icon={<Settings2 className="w-4 h-4" />} title={t('media_settings')} />

                        <div className="space-y-4">
                            {/* Mode Selection */}
                            <div className="grid grid-cols-3 gap-2">
                                {(['auto', 'single', 'batch'] as const).map(mode => (
                                    <button
                                        key={mode}
                                        onClick={() => setMultiMode(mode)}
                                        className={cn(
                                            "py-2.5 rounded-lg text-[10px] font-black uppercase tracking-widest border transition-all",
                                            multiMode === mode
                                                ? "bg-primary border-primary text-white shadow-lg shadow-primary/20"
                                                : "bg-black/20 border-white/5 text-muted-foreground hover:border-white/20 hover:text-foreground"
                                        )}
                                    >
                                        {{
                                            'auto': 'Auto Detect',
                                            'single': 'Single Item',
                                            'batch': 'Batch Mode'
                                        }[mode]}
                                    </button>
                                ))}
                            </div>

                            {/* Force Refresh Toggle (Always visible) */}
                            <div className="animate-in fade-in slide-in-from-top-1 mt-2">
                                <button
                                    onClick={() => setForceFresh(!forceFresh)}
                                    className={cn(
                                        "w-full py-2.5 rounded-lg text-[10px] font-black uppercase tracking-widest border transition-all flex items-center justify-center gap-2",
                                        forceFresh
                                            ? "bg-red-500/10 border-red-500 text-red-400 shadow-[0_0_10px_rgba(239,68,68,0.2)]"
                                            : "bg-black/20 border-white/5 text-muted-foreground hover:border-white/20 hover:text-foreground"
                                    )}
                                >
                                    <div className={cn("w-1.5 h-1.5 rounded-full", forceFresh ? "bg-red-500 animate-pulse" : "bg-white/20")} />
                                    Force Refresh (Overwrite)
                                </button>
                            </div>

                            <div className="h-px bg-white/5" />

                            <div className="grid grid-cols-3 gap-2">
                                {['', 'movie', 'tv'].map(type => (
                                    <button
                                        key={type}
                                        onClick={() => setMediaType(type)}
                                        className={cn(
                                            "py-2.5 rounded-lg text-[10px] font-black uppercase tracking-widest border transition-all",
                                            mediaType === type
                                                ? "bg-primary border-primary text-white shadow-lg shadow-primary/20"
                                                : "bg-black/20 border-white/5 text-muted-foreground hover:border-white/20 hover:text-foreground"
                                        )}
                                    >
                                        {type || "Auto"}
                                    </button>
                                ))}
                            </div>

                            <div className="space-y-2">
                                <label className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest px-1">
                                    {t('tmdb_id_label' as any)}
                                </label>
                                <div className="relative">
                                    <input
                                        type="number"
                                        placeholder="e.g. 550"
                                        value={tmdbId}
                                        onChange={(e) => setTmdbId(e.target.value)}
                                        className="w-full bg-black/20 border border-white/5 focus:border-primary/50 focus:ring-1 focus:ring-primary/20 rounded-xl px-4 py-3 text-sm outline-none transition-all placeholder:text-white/10"
                                    />
                                    <div className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-bold text-primary/50 pointer-events-none">TMDB</div>
                                </div>
                            </div>
                        </div>

                        {/* Search Mode */}
                        <div className="pt-4 border-t border-white/5 space-y-3">
                            <div className="grid grid-cols-3 gap-2">
                                <button
                                    onClick={() => setSearchMode('smart')}
                                    className={cn(
                                        "py-3 rounded-xl border text-[9px] font-bold uppercase tracking-tighter transition-all",
                                        searchMode === 'smart' ? "bg-primary/10 border-primary text-primary" : "bg-black/10 border-white/5 text-muted-foreground"
                                    )}
                                >
                                    {t('search_mode_smart')}
                                </button>
                                <button
                                    onClick={() => setSearchMode('tmdb_only')}
                                    className={cn(
                                        "py-3 rounded-xl border text-[9px] font-bold uppercase tracking-tighter transition-all",
                                        searchMode === 'tmdb_only' ? "bg-primary/10 border-primary text-primary" : "bg-black/10 border-white/5 text-muted-foreground"
                                    )}
                                >
                                    {t('search_mode_tmdb_only')}
                                </button>
                                <button
                                    onClick={() => setSearchMode('tavily_only')}
                                    className={cn(
                                        "py-3 rounded-xl border text-[9px] font-bold uppercase tracking-tighter transition-all",
                                        searchMode === 'tavily_only' ? "bg-primary/10 border-primary text-primary" : "bg-black/10 border-white/5 text-muted-foreground"
                                    )}
                                >
                                    {t('search_mode_tavily_only')}
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* Advanced Advanced */}
                    <div className="glass-panel rounded-2xl p-5 space-y-5">
                        <div className="flex items-center gap-2 justify-between">
                            <TogglePill active={useLocalNfo} onClick={() => setUseLocalNfo(!useLocalNfo)} label={t('opt_local_nfo')} icon={<FileText className="w-3 h-3" />} />
                            <TogglePill active={extraImages} onClick={() => setExtraImages(!extraImages)} label={t('opt_extra_images')} icon={<FileImage className="w-3 h-3" />} />
                        </div>

                        <div className="space-y-2.5 pt-2">
                            <div className="flex justify-between items-center px-1">
                                <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">{t('concurrency')}</span>
                                <span className="text-xs font-mono text-primary font-bold">{workers} {t('threads')}</span>
                            </div>
                            <input
                                type="range" min="1" max="16" step="1"
                                value={workers} onChange={(e) => setWorkers(parseInt(e.target.value))}
                                className="w-full h-1.5 bg-black/40 rounded-lg appearance-none cursor-pointer accent-primary"
                            />
                        </div>
                    </div>

                    {strategy === 'organize' && (
                        <div className="flex items-center gap-3 p-4 rounded-xl bg-orange-500/10 border border-orange-500/20 text-orange-400 animate-pulse">
                            <AlertCircle className="w-5 h-5 shrink-0" />
                            <p className="text-[10px] font-bold leading-tight uppercase tracking-wider">{t('warning_inplace')}</p>
                        </div>
                    )}
                </div>

                {/* Right: Task Board Panel (8/12) */}

                {/* Resizer Handle */}
                <div
                    onMouseDown={startResizing}
                    className="w-4 flex items-center justify-center cursor-col-resize hover:bg-white/5 group transition-colors relative z-50 shrink-0 select-none"
                >
                    <div className="w-1 h-8 rounded-full bg-white/10 group-hover:bg-primary/50 transition-colors" />
                </div>

                {/* Right: Task Board Panel (Flexible) */}
                <div className="flex-1 min-w-0 flex flex-col h-full overflow-hidden">
                    <TaskBoard defaultConfig={{ strategy, outputPath, forceFresh }} />
                </div>
            </div>
            {/* Folder Picker Modal */}
            {showPicker && (
                <div
                    className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-8 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200"
                    onClick={() => setShowPicker(null)}
                >
                    <div
                        className="w-full max-w-2xl bg-[#0a0c10]/95 border border-white/10 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh] animate-in zoom-in-95 duration-200"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="p-6 border-b border-white/5 flex items-center justify-between bg-gradient-to-r from-white/5 to-transparent">
                            <div className="flex items-center gap-3">
                                <div className="w-10 h-10 rounded-2xl bg-primary/20 flex items-center justify-center text-primary">
                                    <FolderOpen className="w-5 h-5" />
                                </div>
                                <div>
                                    <h3 className="font-bold text-lg text-white/90">{t('modal_title')}</h3>
                                    <p className="text-xs text-white/40 uppercase tracking-widest font-bold">{t('modal_subtitle')}</p>
                                </div>
                            </div>
                            <button
                                onClick={() => setShowPicker(null)}
                                className="p-2 hover:bg-white/10 rounded-full text-white/40 hover:text-white transition-colors"
                            >
                                <X className="w-5 h-5" />
                            </button>
                        </div>
                        <div className="flex-1 overflow-auto p-2 scrollbar-thin">
                            <FolderPicker
                                className="h-full"
                                initialPath={showPicker === 'input' ? selectedPath : outputPath}
                                onSelect={(path) => {
                                    if (showPicker === 'input') setSelectedPath(path);
                                    else setOutputPath(path);
                                }}
                            />
                        </div>
                        <div className="p-4 border-t border-white/5 bg-white/5 flex justify-end gap-3">
                            <button
                                onClick={() => setShowPicker(null)}
                                className="px-6 py-2.5 rounded-xl text-sm font-bold bg-primary text-white hover:bg-primary/90 transition-all shadow-lg shadow-primary/20"
                            >
                                {t('confirm_selection') || "Confirm"}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

// --- Subcomponents ---

function SectionHeader({ icon, title }: { icon: any, title: string }) {
    return (
        <div className="flex items-center gap-2 px-1">
            <div className="text-primary">{icon}</div>
            <h4 className="text-[10px] font-black uppercase tracking-[0.2em] text-muted-foreground">{title}</h4>
        </div>
    );
}

function ModeCard({ active, onClick, icon, title, desc, accent = "primary" }: any) {
    const accentClass = {
        primary: active ? "border-primary bg-primary/10 text-primary" : "border-white/5 bg-black/20 text-muted-foreground",
        orange: active ? "border-orange-500 bg-orange-500/10 text-orange-400" : "border-white/5 bg-black/20 text-muted-foreground",
        blue: active ? "border-blue-500 bg-blue-500/10 text-blue-400" : "border-white/5 bg-black/20 text-muted-foreground"
    }[accent as 'primary' | 'orange' | 'blue'];

    return (
        <div
            onClick={onClick}
            className={cn(
                "group relative flex items-start gap-4 p-4 rounded-2xl border transition-all duration-300 cursor-pointer overflow-hidden",
                accentClass,
                !active && "hover:border-white/20 hover:bg-white/5"
            )}
        >
            <div className={cn(
                "w-10 h-10 rounded-xl flex items-center justify-center shrink-0 transition-transform duration-500 group-hover:scale-110",
                active ? "bg-white/10" : "bg-black/20"
            )}>
                {icon}
            </div>
            <div className="flex-1 min-w-0">
                <div className={cn("text-xs font-black uppercase tracking-widest", active ? "text-foreground" : "text-muted-foreground opacity-80")}>
                    {title}
                </div>
                <p className="text-[10px] font-medium leading-relaxed mt-1 opacity-60 line-clamp-2">
                    {desc}
                </p>
            </div>
            {active && (
                <div className="absolute top-0 right-0 p-2">
                    <div className="w-1.5 h-1.5 rounded-full bg-current shadow-[0_0_8px_currentColor]" />
                </div>
            )}
        </div>
    );
}

function TogglePill({ active, onClick, label, icon }: any) {
    return (
        <button
            onClick={onClick}
            className={cn(
                "flex-1 flex items-center justify-center gap-2 py-3 px-2 rounded-xl border text-[10px] font-bold uppercase tracking-tighter transition-all",
                active ? "bg-primary/10 border-primary text-primary" : "bg-black/20 border-white/5 text-muted-foreground hover:border-white/10"
            )}
        >
            {icon}
            <span>{label}</span>
        </button>
    );
}
