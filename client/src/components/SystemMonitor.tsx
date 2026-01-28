
import { useEffect, useState } from 'react';
import { Activity, Zap, BarChart3, Database, Loader2 } from 'lucide-react';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/language';

interface SystemStats {
    running: boolean;
    workers: number;
    stats: {
        total_tasks: number;
        total_media: number;
        total_success: number;
        total_failed: number;
        total_duration: number;
    };
}

export function SystemMonitor() {
    const { t } = useTranslation();
    const [stats, setStats] = useState<SystemStats | null>(null);
    const [ping, setPing] = useState<number>(0);

    useEffect(() => {
        const fetchStats = async () => {
            const start = performance.now();
            try {
                const res = await fetch('http://localhost:8000/api/status');
                const data = await res.json();
                setStats(data);
                setPing(Math.round(performance.now() - start));
            } catch (e) {
                setStats(null);
            }
        };

        fetchStats();
        const interval = setInterval(fetchStats, 2000);
        return () => clearInterval(interval);
    }, []);

    const s = stats?.stats || { total_tasks: 0, total_media: 0, total_success: 0, total_failed: 0, total_duration: 0 };
    const successRate = s.total_media ? Math.round((s.total_success / s.total_media) * 100) : 100;

    return (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 p-4 lg:p-6 pb-2">
            {/* Status Card */}
            <div className={cn(
                "relative overflow-hidden rounded-2xl p-4 transition-all duration-300 group",
                "bg-panel/40 backdrop-blur-sm shadow-sm hover:bg-panel/60",
                stats?.running ? "shadow-primary/5" : ""
            )}>
                <div className={cn("absolute inset-0 bg-gradient-to-br from-primary/5 to-transparent transition-opacity duration-500", stats?.running ? "opacity-100" : "opacity-0")} />
                <div className="flex items-center gap-4 relative z-10">
                    <div className={cn(
                        "w-12 h-12 rounded-xl flex items-center justify-center transition-all duration-300",
                        stats?.running ? "bg-primary text-white shadow-lg shadow-primary/20 scale-105" : "bg-muted text-muted-foreground"
                    )}>
                        {stats?.running ? <Activity size={24} className="animate-pulse" /> : <Loader2 size={24} className={stats === null ? "animate-spin" : ""} />}
                    </div>
                    <div>
                        <div className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-0.5">{t('system_status')}</div>
                        <div className={cn("font-bold text-lg leading-none", stats?.running ? "text-primary" : "text-foreground")}>
                            {stats === null ? "Connecting..." : (stats.running ? t('status_online') : t('status_standby'))}
                        </div>
                    </div>
                </div>
            </div>

            {/* Performance Card */}
            <div className="bg-panel/40 backdrop-blur-sm rounded-2xl p-4 flex items-center gap-4 hover:bg-panel/60 transition-all group">
                <div className="w-12 h-12 rounded-xl flex items-center justify-center bg-yellow-500/10 text-yellow-500 group-hover:scale-105 transition-transform duration-300">
                    <Zap size={24} />
                </div>
                <div>
                    <div className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-0.5">{t('performance')}</div>
                    <div className="font-bold text-lg leading-none text-foreground flex items-center gap-2">
                        <span>{stats?.workers || 4} {t('threads')}</span>
                        <span className="text-xs font-normal text-muted-foreground/30">|</span>
                        <span className={cn("text-xs font-mono", ping > 100 ? "text-yellow-500" : "text-emerald-500")}>{ping}ms</span>
                    </div>
                </div>
            </div>

            {/* Throughput Card */}
            <div className="bg-panel/40 backdrop-blur-sm rounded-2xl p-4 flex items-center gap-4 hover:bg-panel/60 transition-all group">
                <div className="w-12 h-12 rounded-xl flex items-center justify-center bg-blue-500/10 text-blue-500 group-hover:scale-105 transition-transform duration-300">
                    <Database size={24} />
                </div>
                <div>
                    <div className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-0.5">{t('processed')}</div>
                    <div className="font-bold text-lg leading-none text-foreground">
                        {s.total_media} <span className="text-sm font-normal text-muted-foreground">{t('items')}</span>
                    </div>
                </div>
            </div>

            {/* Success Rate Card */}
            <div className="bg-panel/40 backdrop-blur-sm rounded-2xl p-4 flex items-center gap-4 hover:bg-panel/60 transition-all group">
                <div className={cn(
                    "w-12 h-12 rounded-xl flex items-center justify-center transition-colors group-hover:scale-105 duration-300",
                    successRate < 90 ? "bg-red-500/10 text-red-500" : "bg-emerald-500/10 text-emerald-500"
                )}>
                    <BarChart3 size={24} />
                </div>
                <div>
                    <div className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-0.5">{t('success_rate')}</div>
                    <div className={cn("font-bold text-lg leading-none", successRate < 90 ? "text-red-500" : "text-emerald-500")}>
                        {successRate}%
                        <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded-full bg-surface text-muted-foreground font-normal">
                            {s.total_failed} {t('status_failed')}
                        </span>
                    </div>
                </div>
            </div>
        </div>
    );
}
