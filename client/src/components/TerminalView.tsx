
import { useEffect, useRef, useState } from 'react';
import { cn } from '../lib/utils';
import { Terminal as TerminalIcon } from 'lucide-react';
import { useTranslation } from '../lib/language';

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
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//localhost:8000/ws/logs`;

            const ws = new WebSocket(wsUrl);
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
        <div className={cn("flex flex-col rounded-lg overflow-hidden border shadow-2xl font-mono text-sm bg-slate-50 dark:bg-black border-slate-200 dark:border-slate-800", className)}>
            {/* Header */}
            <div className="flex items-center px-4 py-2 bg-slate-200 dark:bg-slate-900 border-b border-slate-300 dark:border-slate-800">
                <TerminalIcon className="w-4 h-4 mr-2 text-primary" />
                <span className="text-slate-700 dark:text-slate-300 font-semibold">{t('live_logs')}</span>
            </div>

            {/* Content */}
            <div className="flex-1 p-4 overflow-y-auto h-[400px] scrollbar-thin scrollbar-thumb-slate-300 dark:scrollbar-thumb-slate-700 scrollbar-track-transparent">
                {logs.length === 0 && <span className="text-slate-500 dark:text-slate-600 italic">{t('waiting_logs')}</span>}
                {logs.map((log, i) => (
                    <div key={i} className="whitespace-pre-wrap text-slate-800 dark:text-slate-300 leading-tight mb-1 animate-in fade-in duration-300">
                        {log}
                    </div>
                ))}
                <div ref={bottomRef} />
            </div>
        </div>
    );
}
