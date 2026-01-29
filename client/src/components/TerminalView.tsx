
import { useEffect, useRef, useState } from 'react';
import { cn } from '../lib/utils';
import { Terminal as TerminalIcon } from 'lucide-react';
import { useTranslation } from '../lib/language';
import { wsUrl } from '../lib/api';

interface TerminalViewProps {
    className?: string;
}

export function TerminalView({ className }: TerminalViewProps) {
    const { t } = useTranslation();
    const [logs, setLogs] = useState<string[]>([]);
    const bottomRef = useRef<HTMLDivElement>(null);
    const wsRef = useRef<WebSocket | null>(null);

    useEffect(() => {
        let reconnectTimer: any;

        const connect = () => {
            const ws = new WebSocket(wsUrl('/ws/logs'));
            wsRef.current = ws;

            ws.onopen = () => {
                setLogs(prev => [...prev, "--- Connected to Log Stream ---"]);
                if (reconnectTimer) {
                    clearInterval(reconnectTimer);
                    reconnectTimer = null;
                }
            };

            ws.onmessage = (event) => {
                const msg = event.data;
                setLogs(prev => {
                    const newLogs = [...prev, msg];
                    if (newLogs.length > 1000) return newLogs.slice(newLogs.length - 1000);
                    return newLogs;
                });
            };

            ws.onclose = () => {
                setLogs(prev => [...prev, "--- Connection Closed. Retrying... ---"]);
                if (!reconnectTimer) {
                    reconnectTimer = setInterval(connect, 3000);
                }
            };

            ws.onerror = () => {
                ws.close();
            };
        };

        connect();

        return () => {
            if (wsRef.current) wsRef.current.close();
            if (reconnectTimer) clearInterval(reconnectTimer);
        };
    }, []);

    // Auto-scroll
    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [logs]);

    return (
        <div className={cn("glass-panel-pro rounded-3xl w-full h-full flex flex-col overflow-hidden shadow-xl border border-glass-border", className)}>
            {/* Header */}
            <div className="flex items-center px-6 py-4 border-b border-white/5 bg-black/5">
                <TerminalIcon className="w-4 h-4 mr-3 text-primary" />
                <span className="text-text-main font-bold text-xs uppercase tracking-widest">{t('live_logs')}</span>
                <div className="ml-auto flex gap-1.5 opacity-50">
                    <div className="w-2.5 h-2.5 rounded-full bg-red-500/20" />
                    <div className="w-2.5 h-2.5 rounded-full bg-yellow-500/20" />
                    <div className="w-2.5 h-2.5 rounded-full bg-emerald-500/20" />
                </div>
            </div>

            {/* Content */}
            <div className="flex-1 p-6 overflow-y-auto scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent bg-black/40 font-mono text-xs">
                {logs.length === 0 && <span className="text-text-muted/50 italic">{t('waiting_logs')}</span>}
                {logs.map((log, i) => (
                    <div key={i} className="whitespace-pre-wrap text-text-muted/80 hover:text-text-main leading-relaxed mb-0.5 border-l-2 border-transparent hover:border-primary/50 pl-2 -ml-2 transition-colors">
                        <span className="opacity-30 mr-2 select-none text-primary">›</span>
                        {log}
                    </div>
                ))}
                <div ref={bottomRef} />
            </div>
        </div>
    );
}
