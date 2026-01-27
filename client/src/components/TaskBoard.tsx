import { useState, useEffect, useRef } from 'react';
import {
    CheckCircle2, AlertCircle, Loader2, Search,
    LayoutGrid, List, FileVideo,
    Terminal as TerminalIcon, Play
} from 'lucide-react';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/language';
import { motion, AnimatePresence } from 'framer-motion';

interface Task {
    threadId: string;
    name: string;
    tmdbId?: string;
    mediaType?: string;
    fullPath?: string; // Stored for execution
    status: 'idle' | 'searching' | 'fetching' | 'processing' | 'completed' | 'failed' | 'dry_run' | 'audit_completed';
    step: string;
    lastLog: string;
    logs: string[];
    isExpanded: boolean;
}

export function TaskBoard() {
    const { t } = useTranslation();
    const [tasks, setTasks] = useState<Record<string, Task>>({});
    const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
    const [showRaw, setShowRaw] = useState(false);
    const [rawLogs, setRawLogs] = useState<string[]>([]);
    const wsRef = useRef<WebSocket | null>(null);

    // Consolidation Refs
    const aliases = useRef<Record<string, string>>({}); // threadId -> primaryThreadId
    const taskNames = useRef<Record<string, string>>({}); // Name -> primaryThreadId (for merging)

    // Function to execute a task from audit state
    const handleExecute = async (task: Task) => {
        if (!task.fullPath || !task.tmdbId) return;

        try {
            await fetch('http://localhost:8000/api/tasks/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    input_dir: task.fullPath,
                    tmdb_id: parseInt(task.tmdbId),
                    media_type: task.mediaType,
                    dry_run: false,
                })
            });
        } catch (e) {
            console.error("Failed to start task", e);
        }
    };

    useEffect(() => {
        const connect = () => {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const ws = new WebSocket(`${protocol}//localhost:8000/ws/logs`);
            wsRef.current = ws;

            ws.onmessage = (event) => {
                const msg = event.data;
                setRawLogs(prev => [...prev.slice(-200), msg]);
                parseLog(msg);
            };

            ws.onclose = () => setTimeout(connect, 3000);
        };

        connect();
        return () => wsRef.current?.close();
    }, []);

    const parseLog = (log: string) => {
        // Pattern: 2026-01-26 21:55:00 [Thread-1] INFO - Message
        const match = log.match(/\[(.*?)\]\s+(\w+)\s+-\s+(.*)/);
        if (!match) return;

        const [, threadIdRaw, , message] = match;
        // Ignore main thread logs unless necessary? For task tracking we usually ignore MainThread/JobManager
        // But JobManager might log "Input: ..." which helps? For now, stick to worker threads.
        if (threadIdRaw === 'MainThread' || threadIdRaw.startsWith('AnyIO') || threadIdRaw.startsWith('JobManager')) return;

        // Resolve Alias
        let primaryThreadId = aliases.current[threadIdRaw] || threadIdRaw;

        // Task Name Extraction for Merging
        let detectedName = '';
        if (message.includes('Processing: ')) {
            const parts = message.match(/Processing:\s+(.*?)\s+\(ID:/);
            if (parts) detectedName = parts[1];
        }

        // Apply Merging Logic
        if (detectedName) {
            const existingId = taskNames.current[detectedName];
            if (existingId && existingId !== primaryThreadId) {
                // Merge detected! This thread is working on an existing task.
                aliases.current[threadIdRaw] = existingId;
                primaryThreadId = existingId;
            } else if (!existingId) {
                taskNames.current[detectedName] = primaryThreadId;
            }
        }

        setTasks(prev => {
            const existing = prev[primaryThreadId] || {
                threadId: primaryThreadId,
                name: t('initializing'),
                status: 'idle',
                step: t('preparing'),
                lastLog: '',
                logs: [],
                isExpanded: false
            };

            const updated = { ...existing };
            updated.lastLog = message;
            updated.logs = [...updated.logs.slice(-50), message];

            // Parsing logic
            if (message.includes('Processing: ')) {
                const parts = message.match(/Processing:\s+(.*?)\s+\(ID:\s+(.*?),\s+Query:\s+(.*?),\s+Type:\s+(.*?)\)/);
                if (parts) {
                    updated.name = parts[1];
                    updated.tmdbId = parts[2] !== 'None' ? parts[2] : undefined;
                    updated.mediaType = parts[4];
                    updated.status = 'processing';
                    updated.step = t('scanning');
                }
            } else if (message.includes('🕵️ AUDIT_HIT:')) {
                // Parse Audit Hit
                const pathMatch = message.match(/Path='(.*?)'/);
                const idMatch = message.match(/ID=(\d+)/);
                const titleMatch = message.match(/Title='(.*?)'/);
                const typeMatch = message.match(/Type='(.*?)'/);

                if (pathMatch) updated.fullPath = pathMatch[1];
                if (idMatch) updated.tmdbId = idMatch[1];
                // Ignore 'None' title
                if (titleMatch && titleMatch[1] !== 'None') updated.name = titleMatch[1];
                if (typeMatch) updated.mediaType = typeMatch[1];

                updated.status = 'dry_run';
                updated.step = t('audit_result');
                updated.lastLog = `Audit: Found ${updated.name} (ID: ${updated.tmdbId})`;
            } else if (message.includes('🔍 TMDB failed')) {
                updated.status = 'searching';
                updated.step = t('extended_search');
            } else if (message.includes('✅ Selected Candidate:')) {
                const idMatch = message.match(/TMDB ID (\d+)/);
                const titleMatch = message.match(/Title='(.*?)'/);
                const typeMatch = message.match(/\(Type: (\w+)\)/);

                if (idMatch) updated.tmdbId = idMatch[1];
                if (titleMatch && titleMatch[1] !== 'None') updated.name = titleMatch[1];
                if (typeMatch) updated.mediaType = typeMatch[1];

                updated.status = 'fetching';
                updated.step = t('metadata_match');
            } else if (message.includes('📡 Processing full metadata')) {
                updated.step = t('episodes_details');
            } else if (message.includes('Renamed:')) {
                updated.step = t('organizing');
            } else if (message.includes('Would process directory:')) {
                updated.status = 'dry_run';
                updated.step = t('audit_result');
                const parts = message.match(/Would process directory:\s+(.*)/);
                if (parts) updated.name = parts[1].split('/').pop() || 'Unknown';
            } else if (message.includes('Metadata generation failed')) {
                updated.status = 'failed';
                updated.step = t('error');
            } else if (message.includes('Audit completed')) {
                updated.step = t('status_audit_complete');
                updated.status = 'audit_completed';
            }

            // Success detection
            if (message.includes('🏆 Task Successfully Finished:') ||
                message.includes('Renamed Directory:') ||
                (updated.status === 'processing' && message.includes('successful'))) {
                updated.status = 'completed';
                updated.step = t('finished');
            }

            return { ...prev, [primaryThreadId]: updated };
        });
    };

    const taskList = Object.values(tasks).sort((a, b) => b.threadId.localeCompare(a.threadId));

    return (
        <div className="flex flex-col h-full bg-black/40 backdrop-blur-xl rounded-2xl border border-white/5 overflow-hidden shadow-2xl">
            {/* Toolbar */}
            <div className="flex items-center justify-between px-6 py-4 bg-white/5 border-b border-white/5">
                <div className="flex items-center gap-3">
                    <div className="w-2 h-2 rounded-full bg-primary animate-pulse shadow-[0_0_10px_var(--primary)]" />
                    <h3 className="font-bold text-sm uppercase tracking-widest text-white/80">{t('mission_control')}</h3>
                </div>

                <div className="flex items-center gap-2">
                    <div className="flex bg-black/40 rounded-lg p-1 mr-4 border border-white/5">
                        <button
                            onClick={() => setViewMode('grid')}
                            className={cn("p-1.5 rounded-md transition-all", viewMode === 'grid' ? "bg-primary/20 text-primary shadow-inner" : "text-white/40 hover:text-white/60")}
                        >
                            <LayoutGrid className="w-4 h-4" />
                        </button>
                        <button
                            onClick={() => setViewMode('list')}
                            className={cn("p-1.5 rounded-md transition-all", viewMode === 'list' ? "bg-primary/20 text-primary shadow-inner" : "text-white/40 hover:text-white/60")}
                        >
                            <List className="w-4 h-4" />
                        </button>
                    </div>

                    <button
                        onClick={() => setShowRaw(!showRaw)}
                        className={cn(
                            "flex items-center gap-2 px-3 py-1.5 rounded-lg border text-[10px] font-bold uppercase transition-all",
                            showRaw ? "bg-primary border-primary text-white" : "border-white/10 text-white/60 hover:border-white/20"
                        )}
                    >
                        <TerminalIcon className="w-3.5 h-3.5" />
                        {t('console')}
                    </button>
                </div>
            </div>

            {/* Content Area */}
            <div className="flex-1 overflow-y-auto p-6 scrollbar-thin">
                {taskList.length === 0 ? (
                    <div className="h-full flex flex-col items-center justify-center text-white/20 space-y-4">
                        <Search className="w-12 h-12 stroke-[1]" />
                        <p className="text-sm font-medium uppercase tracking-widest italic">{t('waiting_missions')}</p>
                    </div>
                ) : (
                    <div className={cn(
                        "grid gap-4 transition-all duration-500",
                        viewMode === 'grid' ? "grid-cols-1 md:grid-cols-2 xl:grid-cols-3" : "grid-cols-1"
                    )}>
                        <AnimatePresence mode="popLayout">
                            {taskList.map(task => (
                                <TaskCard key={task.threadId} task={task} mode={viewMode} onExecute={handleExecute} />
                            ))}
                        </AnimatePresence>
                    </div>
                )}
            </div>

            {/* Raw Log Overlay (Optional/Collapsible) */}
            <AnimatePresence>
                {showRaw && (
                    <motion.div
                        initial={{ height: 0 }}
                        animate={{ height: 200 }}
                        exit={{ height: 0 }}
                        className="bg-[#050505] border-t border-white/10 overflow-hidden"
                    >
                        <div className="p-4 font-mono text-[10px] text-white/40 overflow-y-auto h-full scrollbar-none">
                            {rawLogs.map((l, i) => <div key={i} className="mb-0.5 border-l border-white/5 pl-2">{l}</div>)}
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}

function TaskCard({ task, mode, onExecute }: { task: Task, mode: 'grid' | 'list', onExecute: (t: Task) => void }) {
    const { t } = useTranslation();

    // Status color mapping with audit support
    const statusColor = {
        idle: 'text-slate-500 bg-slate-500/10',
        searching: 'text-amber-400 bg-amber-400/10',
        fetching: 'text-cyan-400 bg-cyan-400/10',
        processing: 'text-blue-400 bg-blue-400/10',
        completed: 'text-emerald-400 bg-emerald-400/10',
        failed: 'text-red-400 bg-red-400/10',
        dry_run: 'text-cyan-400 bg-cyan-400/10 border-cyan-500/30',
        audit_completed: 'text-cyan-400 bg-cyan-400/10 border-cyan-500/30'
    }[task.status] || 'text-slate-400 bg-slate-400/10';

    const isCompact = mode === 'list';
    const isAuditReady = (task.status === 'dry_run' || task.status === 'audit_completed') && task.fullPath && task.tmdbId;

    // Helper to translate status safely
    const getStatusLabel = (s: string) => {
        if (s === 'completed') return t('status_completed');
        if (s === 'failed') return t('status_failed');
        if (s === 'audit_completed') return t('status_audit_complete');
        // @ts-ignore
        return t(s) || s;
    };

    return (
        <motion.div
            layout
            initial={{ opacity: 0, scale: 0.98, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: -10 }}
            className={cn(
                "group relative bg-white/[0.04] hover:bg-white/[0.08] border border-white/5 hover:border-white/10 rounded-xl p-4 transition-all duration-300 overflow-hidden shadow-sm hover:shadow-md",
                task.status === 'completed' && "border-emerald-500/20 shadow-[0_0_20px_-10px_rgba(16,185,129,0.2)]",
                task.status === 'failed' && "border-red-500/20 shadow-[0_0_20px_-10px_rgba(239,68,68,0.2)]",
                isAuditReady && "border-cyan-500/30 shadow-[0_0_15px_-5px_var(--cyan-500)_inset]"
            )}
        >
            {/* Top Status Gradient Line */}
            <div className={cn(
                "absolute top-0 left-0 w-full h-[3px] opacity-30",
                statusColor?.split(' ')[0].replace('text-', 'bg-')
            )} />

            {/* Absolute Status Badge (Top Right) - Re-positioned to be clean */}
            {!isCompact && (
                <div className="absolute top-3 right-3 z-20">
                    <span className={cn(
                        "px-2 py-0.5 rounded-md text-[9px] font-bold uppercase tracking-wider border border-white/5 transition-colors shadow-sm",
                        statusColor
                    )}>
                        {getStatusLabel(task.status)}
                    </span>
                </div>
            )}

            <div className={cn("flex gap-4", isCompact ? "items-center" : "")}>
                {/* 1. Icon Section (Left) */}
                <div className={cn(
                    "flex items-center justify-center rounded-lg shrink-0 transition-all duration-500 group-hover:scale-105 bg-black/20 border border-white/5",
                    task.mediaType === 'tv' ? "text-indigo-400 group-hover:text-indigo-300" : "text-orange-400 group-hover:text-orange-300",
                    isCompact ? "w-10 h-10" : "w-14 h-14"
                )}>
                    {task.mediaType === 'tv' ? <LayoutGrid className="w-6 h-6" /> : <FileVideo className="w-6 h-6" />}
                </div>

                {/* 2. Main Content (Right) */}
                <div className="flex-1 min-w-0 flex flex-col justify-center">

                    {/* Header: Title */}
                    <div className="flex items-start justify-between gap-4 mb-1">
                        <h4 className={cn(
                            "font-bold text-sm text-white/90 truncate group-hover:text-white transition-colors leading-tight",
                            !isCompact && "pr-24" // Reserve space for the absolute status badge
                        )} title={task.name}>
                            {task.name}
                        </h4>

                        {/* List Mode Status (Inline) */}
                        {isCompact && (
                            <span className={cn(
                                "px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wide shrink-0 border border-white/5",
                                statusColor
                            )}>
                                {getStatusLabel(task.status)}
                            </span>
                        )}
                    </div>

                    {/* Metadata Row */}
                    <div className="flex items-center gap-3 text-[10px] text-white/40 font-mono mb-2">
                        <span className="opacity-60">{task.threadId}</span>
                        {task.tmdbId && <span className="text-primary/70 font-semibold tracking-wider">TMDB:{task.tmdbId}</span>}
                    </div>

                    {/* Action & Progress Area (Grid Mode) */}
                    {!isCompact && (
                        <div className="space-y-2.5">

                            {/* Execute Plan Button - Full Width if Ready */}
                            {isAuditReady ? (
                                <button
                                    onClick={(e) => { e.stopPropagation(); onExecute(task); }}
                                    className="w-full py-1.5 bg-gradient-to-r from-cyan-500/20 to-blue-500/20 hover:from-cyan-500/30 hover:to-blue-500/30 text-cyan-300 hover:text-cyan-100 text-[11px] font-bold uppercase tracking-wider rounded-lg flex items-center justify-center gap-2 border border-cyan-500/30 transition-all hover:scale-[1.02] active:scale-[0.98] shadow-lg shadow-cyan-900/20 cursor-pointer group/btn"
                                >
                                    <Play className="w-3 h-3 fill-current group-hover/btn:animate-pulse" />
                                    {t('execute_plan')}
                                </button>
                            ) : (
                                /* Progress Bar (Only when NOT audit ready) */
                                <div className="space-y-1.5">
                                    <div className="relative h-1 w-full bg-white/5 rounded-full overflow-hidden">
                                        <motion.div
                                            className={cn("absolute inset-y-0 left-0 bg-primary/80",
                                                task.status === 'completed' && "bg-emerald-500",
                                                task.status === 'failed' && "bg-red-500"
                                            )}
                                            animate={{
                                                width: task.status === 'completed' ? '100%' :
                                                    task.status === 'fetching' ? '70%' :
                                                        task.status === 'processing' ? '40%' : '10%'
                                            }}
                                            transition={{ duration: 0.5 }}
                                        />
                                    </div>
                                    <div className="flex items-center justify-between text-[10px] text-white/30 truncate">
                                        <span className="truncate">{task.step}</span>
                                        {task.status === 'completed' && <CheckCircle2 className="w-3 h-3 text-emerald-500/80" />}
                                    </div>
                                </div>
                            )}

                            {/* Audit Result Log Preview */}
                            {isAuditReady && task.lastLog && (
                                <p className="text-[9px] text-cyan-400/60 font-mono truncate pl-1 border-l-2 border-cyan-500/20">
                                    {task.lastLog.replace('🕵️ AUDIT_HIT:', '')}
                                </p>
                            )}
                        </div>
                    )}
                </div>
            </div>

            {/* List Mode Log */}
            {isCompact && (
                <div className="ml-4 text-[10px] font-mono text-white/20 truncate italic flex-1">
                    {task.lastLog}
                </div>
            )}
        </motion.div>
    );
}
