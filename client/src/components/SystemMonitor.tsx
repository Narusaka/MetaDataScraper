
import { useEffect, useState } from 'react';
import { Activity, Zap, BarChart3, Database } from 'lucide-react';
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
        <div className="grid grid-cols-4 gap-4 p-4 bg-surface/50 border-b border-border backdrop-blur-sm">
            {/* Status Card */}
            <div className="bg-panel border border-border rounded-lg p-3 flex items-center gap-4 relative overflow-hidden group shadow-sm transition-all hover:shadow-md hover:border-border/80">
                <div className={cn("absolute inset-0 bg-gradient-to-r from-primary/10 to-transparent transition-opacity", stats?.running ? "opacity-100" : "opacity-0")} />
                <div className={cn("w-10 h-10 rounded-full flex items-center justify-center bg-surface border border-border z-10 transition-colors", stats?.running ? "animate-pulse border-primary/50 text-primary" : "text-muted-foreground")}>
                    <Activity size={20} />
                </div>
                <div className="z-10">
                    <div className="text-[10px] uppercase font-bold text-secondary tracking-wider">{t('system_status')}</div>
                    <div className={cn("font-mono font-bold text-sm", stats?.running ? "text-primary" : "text-muted-foreground/70")}>
                        {stats?.running ? t('status_online') : t('status_standby')}
                    </div>
                </div>
            </div>

            {/* Performance Card */}
            <div className="bg-panel border border-border rounded-lg p-3 flex items-center gap-4 shadow-sm transition-all hover:shadow-md hover:border-border/80">
                <div className="w-10 h-10 rounded-full flex items-center justify-center bg-surface border border-border text-emerald-500/80">
                    <Zap size={20} />
                </div>
                <div>
                    <div className="text-[10px] uppercase font-bold text-secondary tracking-wider">{t('performance')}</div>
                    <div className="font-mono font-bold text-sm text-text/80 flex items-center gap-2">
                        <span>{stats?.workers || 4} {t('threads')}</span>
                        <span className="text-[10px] text-muted">|</span>
                        <span className={cn("text-xs", ping > 100 ? "text-amber-500" : "text-emerald-500")}>{ping}ms {t('latency')}</span>
                    </div>
                </div>
            </div>

            {/* Throughput Card */}
            <div className="bg-panel border border-border rounded-lg p-3 flex items-center gap-4 shadow-sm transition-all hover:shadow-md hover:border-border/80">
                <div className="w-10 h-10 rounded-full flex items-center justify-center bg-surface border border-border text-violet-500/80">
                    <Database size={20} />
                </div>
                <div>
                    <div className="text-[10px] uppercase font-bold text-secondary tracking-wider">{t('processed')}</div>
                    <div className="font-mono font-bold text-sm text-text/80">
                        {s.total_media} {t('items')} <span className="text-secondary text-xs">({s.total_tasks} {t('batches')})</span>
                    </div>
                </div>
            </div>

            {/* Success Rate Card */}
            <div className="bg-panel border border-border rounded-lg p-3 flex items-center gap-4 shadow-sm transition-all hover:shadow-md hover:border-border/80">
                <div className={cn("w-10 h-10 rounded-full flex items-center justify-center bg-surface border border-border", successRate < 90 ? "text-red-500" : "text-sky-500")}>
                    <BarChart3 size={20} />
                </div>
                <div>
                    <div className="text-[10px] uppercase font-bold text-secondary tracking-wider">{t('success_rate')}</div>
                    <div className={cn("font-mono font-bold text-sm", successRate < 90 ? "text-red-400" : "text-sky-400")}>
                        {successRate}% <span className="text-secondary text-xs">({s.total_failed} {t('status_failed')})</span>
                    </div>
                </div>
            </div>
        </div>
    );
}
