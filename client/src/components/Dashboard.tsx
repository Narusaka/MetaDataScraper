
import { useState, useEffect } from 'react';
import {
    Play, FolderInput, Copy,
    Search, FolderOpen, X
} from 'lucide-react';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/language';
import { FolderPicker } from './FolderPicker';
import { TaskBoard } from './TaskBoard';
import { SystemMonitor } from './SystemMonitor';

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

    return (
        <div className="flex flex-col h-full bg-slate-950 text-slate-100 overflow-hidden font-sans">
            {/* Top Bar: Target Selection & Actions */}
            <div className="shrink-0 h-16 border-b border-slate-800 bg-slate-900/50 flex items-center px-4 gap-4 justify-between">
                <div className="flex items-center gap-4 w-2/3">
                    <div className="flex-1 flex items-center gap-2 bg-slate-900 border border-slate-800 rounded px-3 py-2 group focus-within:border-blue-500/50 transition-colors">
                        <span className="text-xs font-mono font-bold text-blue-500 uppercase">TARGET:</span>
                        <input
                            type="text"
                            value={selectedPath}
                            onChange={(e) => setSelectedPath(e.target.value)}
                            placeholder="/path/to/media"
                            className="flex-1 bg-transparent border-none text-sm text-slate-200 outline-none font-mono placeholder:text-slate-600"
                        />
                        <button onClick={() => setShowPicker('input')} className="text-slate-400 hover:text-white transition-colors">
                            <FolderOpen size={16} />
                        </button>
                    </div>
                </div>

                <div className="flex items-center gap-4">
                    <div className="h-8 w-px bg-slate-800" />
                    <button
                        onClick={handleStart}
                        disabled={isRunning || !selectedPath}
                        className={cn(
                            "flex items-center gap-2 px-8 py-2 rounded bg-blue-600 hover:bg-blue-500 text-white font-bold text-sm tracking-wide uppercase transition-all shadow-[0_0_20px_rgba(37,99,235,0.3)] hover:shadow-[0_0_30px_rgba(37,99,235,0.5)] transform hover:scale-105 active:scale-95 disabled:hover:scale-100 disabled:opacity-50 disabled:cursor-not-allowed disabled:shadow-none",
                            isRunning && "bg-slate-800 text-slate-400"
                        )}
                    >
                        {isRunning ? <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" /> : <Play size={16} fill="currentColor" />}
                        {isRunning ? t('running') : 'EXECUTE'}
                    </button>
                </div>
            </div>

            {/* System Monitor Area */}
            <SystemMonitor />

            {/* Main Content: Sidebar + TaskBoard */}
            <div className="flex-1 flex overflow-hidden">
                {/* Configuration Sidebar */}
                <div className="w-80 shrink-0 bg-slate-900 border-r border-slate-800 flex flex-col overflow-y-auto">

                    {/* Strategy */}
                    <div className="p-4 border-b border-slate-800">
                        <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-3">{t('strategy')}</div>
                        <div className="grid grid-cols-1 gap-1 bg-slate-950 p-1 rounded border border-slate-800">
                            {(['audit', 'organize', 'copy'] as const).map(s => (
                                <button
                                    key={s}
                                    onClick={() => setStrategy(s)}
                                    className={cn(
                                        "flex items-center gap-3 px-3 py-2 rounded text-xs font-bold uppercase tracking-wider text-left transition-colors",
                                        strategy === s ? "bg-slate-800 text-blue-400" : "text-slate-500 hover:text-slate-300 hover:bg-slate-900"
                                    )}
                                >
                                    {s === 'audit' && <Search size={14} />}
                                    {s === 'organize' && <FolderInput size={14} />}
                                    {s === 'copy' && <Copy size={14} />}
                                    {t(`mode_${s}` as any)}
                                </button>
                            ))}
                        </div>
                        {strategy === 'copy' && (
                            <div className="mt-2 pl-2 border-l-2 border-blue-900/50">
                                <label className="text-[9px] text-blue-400 uppercase font-bold block mb-1">Destination:</label>
                                <div className="flex items-center gap-2">
                                    <input
                                        type="text"
                                        value={outputPath}
                                        onChange={(e) => setOutputPath(e.target.value)}
                                        className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 text-xs text-slate-300 font-mono"
                                        placeholder="/path/to/dest"
                                    />
                                    <button onClick={() => setShowPicker('output')} className="text-slate-500 hover:text-blue-400">
                                        <FolderOpen size={14} />
                                    </button>
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Media Settings */}
                    <div className="p-4 flex-1">
                        <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-3">{t('media_settings')}</div>

                        <div className="space-y-4">
                            {/* Type */}
                            <div className="flex gap-1">
                                {['', 'movie', 'tv'].map(type => (
                                    <button
                                        key={type}
                                        onClick={() => setMediaType(type)}
                                        className={cn(
                                            "flex-1 py-1.5 border rounded text-[10px] font-bold uppercase tracking-wider transition-colors",
                                            mediaType === type ? "border-blue-500/50 bg-blue-500/10 text-blue-400" : "border-slate-800 bg-slate-950 text-slate-500 hover:border-slate-700"
                                        )}
                                    >
                                        {type || 'Auto'}
                                    </button>
                                ))}
                            </div>

                            {/* Mode Selection */}
                            <div className="space-y-1">
                                <label className="text-[10px] text-slate-500 font-bold block">Processing Mode</label>
                                <div className="grid grid-cols-3 gap-1">
                                    {(['auto', 'single', 'batch'] as const).map(m => (
                                        <button
                                            key={m}
                                            onClick={() => setMultiMode(m)}
                                            className={cn(
                                                "py-1 rounded text-[9px] font-bold uppercase tracking-wider transition-colors border",
                                                multiMode === m ? "bg-slate-800 border-blue-500/30 text-blue-400" : "bg-slate-950 border-slate-800 text-slate-600 hover:border-slate-700"
                                            )}
                                        >
                                            {m}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            {/* Search Mode */}
                            <div className="space-y-1">
                                <label className="text-[10px] text-slate-500 font-bold block">Search Logic</label>
                                <select
                                    value={searchMode}
                                    onChange={(e) => setSearchMode(e.target.value as any)}
                                    className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1.5 text-xs text-slate-300 outline-none focus:border-blue-500/50"
                                >
                                    <option value="smart">Smart (Hybrid)</option>
                                    <option value="tmdb_only">TMDB Only</option>
                                    <option value="tavily_only">Tavily Only</option>
                                </select>
                            </div>

                            {/* TMDB ID */}
                            <div>
                                <label className="text-[10px] text-slate-500 font-bold block mb-1">TMDB ID (Optional)</label>
                                <input
                                    type="number"
                                    value={tmdbId}
                                    onChange={(e) => setTmdbId(e.target.value)}
                                    className="w-full bg-slate-950 border border-slate-800 rounded px-3 py-2 text-xs font-mono text-slate-300 focus:border-blue-500 outline-none placeholder:text-slate-700"
                                    placeholder="e.g. 12345"
                                />
                            </div>

                            {/* Options */}
                            <div className="space-y-1 pt-2 border-t border-slate-800">
                                <ToggleRow active={useLocalNfo} onClick={() => setUseLocalNfo(!useLocalNfo)} label={t('opt_local_nfo')} />
                                <ToggleRow active={extraImages} onClick={() => setExtraImages(!extraImages)} label={t('opt_extra_images')} />
                                <ToggleRow active={forceFresh} onClick={() => setForceFresh(!forceFresh)} label="Force Refresh" danger />
                            </div>

                            {/* Threads */}
                            <div className="pt-2">
                                <div className="flex justify-between items-center mb-2">
                                    <span className="text-[10px] font-bold text-slate-500 uppercase">Concurrency</span>
                                    <span className="text-xs font-mono text-blue-400">{workers}</span>
                                </div>
                                <input
                                    type="range" min="1" max="16"
                                    value={workers}
                                    onChange={(e) => setWorkers(parseInt(e.target.value))}
                                    className="w-full accent-blue-500 h-1 bg-slate-800 rounded appearance-none cursor-pointer"
                                />
                            </div>
                        </div>
                    </div>
                </div>

                {/* Task Board */}
                <div className="flex-1 bg-slate-950 flex flex-col overflow-hidden relative">
                    <div className="absolute inset-0 z-0 bg-[url('/grid.svg')] opacity-5 pointer-events-none" />
                    <TaskBoard defaultConfig={{ strategy, outputPath, forceFresh }} />
                </div>
            </div>

            {/* Folder Picker Modal */}
            {showPicker && (
                <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-8" onClick={() => setShowPicker(null)}>
                    <div className="w-full max-w-3xl bg-slate-900 border border-slate-700 rounded-lg shadow-2xl flex flex-col max-h-full" onClick={e => e.stopPropagation()}>
                        <div className="h-12 border-b border-slate-800 flex items-center px-4 justify-between bg-slate-800/50">
                            <span className="text-sm font-bold text-slate-200 uppercase tracking-wider">{t('modal_title')}</span>
                            <button onClick={() => setShowPicker(null)} className="text-slate-500 hover:text-white"><X size={18} /></button>
                        </div>
                        <div className="flex-1 overflow-auto p-4 bg-slate-950">
                            <FolderPicker
                                initialPath={showPicker === 'input' ? selectedPath : outputPath}
                                onSelect={(path) => {
                                    if (showPicker === 'input') setSelectedPath(path);
                                    else setOutputPath(path);
                                }}
                            />
                        </div>
                        <div className="p-4 border-t border-slate-800 bg-slate-900 flex justify-end">
                            <button onClick={() => setShowPicker(null)} className="px-6 py-2 bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs uppercase rounded">
                                {t('confirm_selection')}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

function ToggleRow({ active, onClick, label, danger }: { active: boolean, onClick: () => void, label: string, danger?: boolean }) {
    return (
        <button
            onClick={onClick}
            className={cn(
                "w-full flex items-center justify-between px-3 py-2 rounded text-xs transition-colors border border-transparent",
                active
                    ? (danger ? "bg-red-500/10 border-red-500/20 text-red-400" : "bg-blue-500/10 border-blue-500/20 text-blue-400")
                    : "hover:bg-slate-800 text-slate-400"
            )}
        >
            <span className="font-medium">{label}</span>
            <div className={cn("w-2 h-2 rounded-full", active ? (danger ? "bg-red-500" : "bg-blue-500") : "bg-slate-700")} />
        </button>
    )
}
