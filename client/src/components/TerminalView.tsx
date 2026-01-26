
import { useEffect, useRef, useState } from 'react';
import { cn } from '../lib/utils';
import { Terminal as TerminalIcon } from 'lucide-react';

interface TerminalViewProps {
    className?: string;
}

export function TerminalView({ className }: TerminalViewProps) {
    const [logs, setLogs] = useState<string[]>([]);
    const bottomRef = useRef<HTMLDivElement>(null);
    const wsRef = useRef<WebSocket | null>(null);

    useEffect(() => {
        // Connect to WebSocket
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//localhost:8000/ws/logs`;
        console.log("Connecting to WS:", wsUrl);

        try {
            const ws = new WebSocket(wsUrl);
            wsRef.current = ws;

            ws.onopen = () => {
                setLogs(prev => [...prev, "--- Connected to Log Stream ---"]);
            };

            ws.onmessage = (event) => {
                const msg = event.data;
                setLogs(prev => {
                    // Keep last 1000 lines
                    const newLogs = [...prev, msg];
                    if (newLogs.length > 1000) return newLogs.slice(newLogs.length - 1000);
                    return newLogs;
                });
            };

            ws.onerror = (e) => {
                console.error("WebSocket error", e);
                setLogs(prev => [...prev, "!!! WebSocket Connection Error !!!"]);
            };

            ws.onclose = () => {
                setLogs(prev => [...prev, "--- Connection Closed ---"]);
            };

            return () => {
                ws.close();
            };
        } catch (e) {
            console.error("Failed to construct WebSocket", e);
        }
    }, []);

    // Auto-scroll
    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [logs]);

    return (
        <div className={cn("flex flex-col bg-black rounded-lg overflow-hidden border border-slate-700 shadow-2xl font-mono text-sm", className)}>
            {/* Header */}
            <div className="flex items-center px-4 py-2 bg-slate-800 border-b border-slate-700">
                <TerminalIcon className="w-4 h-4 mr-2 text-primary" />
                <span className="text-slate-300">Live Logs</span>
            </div>

            {/* Content */}
            <div className="flex-1 p-4 overflow-y-auto h-[400px] scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent">
                {logs.length === 0 && <span className="text-slate-600 italic">Waiting for logs...</span>}
                {logs.map((log, i) => (
                    <div key={i} className="whitespace-pre-wrap text-slate-300 leading-tight mb-1 animate-in fade-in duration-300">
                        {log}
                    </div>
                ))}
                <div ref={bottomRef} />
            </div>
        </div>
    );
}
