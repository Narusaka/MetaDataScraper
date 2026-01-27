
import { useState, useEffect, useRef } from 'react';
import {
    CheckCircle2, AlertCircle, Loader2, Search,
    LayoutGrid, List, FileVideo,
    Terminal as TerminalIcon
} from 'lucide-react';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/language';
import { motion, AnimatePresence } from 'framer-motion';

interface Task {
    threadId: string;
    name: string;
    tmdbId?: string;
    mediaType?: string;
    status: 'idle' | 'searching' | 'fetching' | 'processing' | 'completed' | 'failed' | 'dry_run';
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

        const [, threadId, , message] = match;
        if (threadId === 'MainThread' || threadId.startsWith('AnyIO') || threadId.startsWith('JobManager')) return;

        setTasks(prev => {
            const existing = prev[threadId] || {
                threadId,
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
            } else if (message.includes('🔍 TMDB failed')) {
                updated.status = 'searching';
                updated.step = t('extended_search');
            } else if (message.includes('✅ Selected Candidate:')) {
                const parts = message.match(/TMDB ID (\d+) \(Type: (\w+)\)/);
                if (parts) {
                    updated.tmdbId = parts[1];
                    updated.mediaType = parts[2];
                }
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
            } else if (message.includes('Batch processing finished')) {
                // Global message, but we can finalize all?
            }

            // Success detection
            if (message.includes('🏆 Task Successfully Finished:') ||
                message.includes('Renamed Directory:') ||
                (updated.status === 'processing' && message.includes('successful'))) {
                updated.status = 'completed';
                updated.step = t('finished');
            }

            return { ...prev, [threadId]: updated };
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
                                <TaskCard key={task.threadId} task={task} mode={viewMode} />
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

function TaskCard({ task, mode }: { task: Task, mode: 'grid' | 'list' }) {
    const statusColor = {
        idle: 'text-slate-500 bg-slate-500/10',
        searching: 'text-amber-400 bg-amber-400/10',
        fetching: 'text-cyan-400 bg-cyan-400/10',
        processing: 'text-blue-400 bg-blue-400/10',
        completed: 'text-emerald-400 bg-emerald-400/10',
        failed: 'text-red-400 bg-red-400/10',
        dry_run: 'text-purple-400 bg-purple-400/10'
    }[task.status];

    const isCompact = mode === 'list';

    return (
        <motion.div
            layout
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: -20 }}
            className={cn(
                "group relative bg-white/[0.03] hover:bg-white/[0.06] border border-white/5 hover:border-white/10 rounded-2xl p-4 transition-colors duration-300 overflow-hidden",
                task.status === 'completed' && "border-emerald-500/20",
                task.status === 'failed' && "border-red-500/20"
            )}
        >
            {/* Status Indicator Bar */}
            <div className={cn(
                "absolute top-0 left-0 w-full h-[2px] opacity-20",
                statusColor?.split(' ')[0].replace('text-', 'bg-')
            )} />

            <div className={cn("flex gap-4", isCompact ? "items-center" : "flex-col")}>
                {/* Icon Section */}
                <div className={cn(
                    "flex items-center justify-center rounded-xl shrink-0 transition-transform duration-500 group-hover:scale-110",
                    task.mediaType === 'tv' ? "bg-indigo-500/10 text-indigo-400" : "bg-orange-500/10 text-orange-400",
                    isCompact ? "w-10 h-10" : "w-12 h-12"
                )}>
                    {task.mediaType === 'tv' ? <LayoutGrid className="w-6 h-6" /> : <FileVideo className="w-6 h-6" />}
                </div>

                {/* Info Section */}
                <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-2 mb-1">
                        <h4 className="font-bold text-sm text-white/90 truncate group-hover:text-white transition-colors">
                            {task.name}
                        </h4>
                        <span className={cn(
                            "px-2 py-0.5 rounded-full text-[8px] font-black uppercase tracking-tighter shrink-0",
                            statusColor
                        )}>
                            {task.status}
                        </span>
                    </div>

                    <div className="flex items-center gap-2 text-[10px] text-white/40 font-mono">
                        <span className="bg-white/5 px-1.5 py-0.5 rounded uppercase tracking-tighter">{task.threadId}</span>
                        {task.tmdbId && <span className="text-primary/60 font-bold tracking-widest">TMDB:{task.tmdbId}</span>}
                    </div>

                    {!isCompact && (
                        <div className="mt-4 space-y-3">
                            {/* Inner Progress Visualization */}
                            <div className="relative h-1 bg-white/5 rounded-full overflow-hidden">
                                <motion.div
                                    className={cn("absolute inset-y-0 left-0 bg-primary", task.status === 'completed' && "bg-emerald-500")}
                                    animate={{
                                        width: task.status === 'completed' ? '100%' :
                                            task.status === 'fetching' ? '70%' :
                                                task.status === 'processing' ? '40%' : '10%'
                                    }}
                                />
                            </div>

                            <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-widest">
                                <span className="text-white/30 flex items-center gap-1.5">
                                    <Loader2 className={cn("w-3 h-3 animate-spin", task.status === 'completed' || task.status === 'failed' ? "hidden" : "block")} />
                                    {task.step}
                                </span>
                                {task.status === 'completed' && <CheckCircle2 className="w-4 h-4 text-emerald-500" />}
                                {task.status === 'failed' && <AlertCircle className="w-4 h-4 text-red-500" />}
                            </div>

                            <p className="text-[10px] font-medium text-white/40 bg-black/20 p-2 rounded-lg truncate border border-white/5">
                                &gt; {task.lastLog || 'Initializing sequence...'}
                            </p>
                        </div>
                    )}
                </div>
            </div>

            {isCompact && (
                <div className="ml-4 text-[10px] font-mono text-white/20 truncate italic flex-1">
                    {task.lastLog}
                </div>
            )}
        </motion.div>
    );
}

