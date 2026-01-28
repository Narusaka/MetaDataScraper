import { useEffect, useState } from 'react';
import { Activity, BarChart3, Database, Cpu } from 'lucide-react';
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

    useEffect(() => {
        const fetchStats = async () => {
            try {
                const res = await fetch('http://localhost:8000/api/status');
                const data = await res.json();
                setStats(data);
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
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 pb-2">
            <MetricCard
                icon={Activity}
                label={t('system_status')}
                value={stats?.running ? "ONLINE" : "STANDBY"}
                subvalue={stats === null ? "Connecting..." : ""}
                color={stats?.running ? "bg-emerald-500" : "bg-yellow-500"}
                delay={0}
            />

            <MetricCard
                icon={Cpu}
                label={t('performance')}
                value={stats?.workers || 4}
                subvalue="THREADS"
                color="bg-blue-500"
                delay={1}
            />

            <MetricCard
                icon={Database}
                label={t('processed')}
                value={s.total_media}
                subvalue="ITEMS"
                color="bg-purple-500"
                delay={2}
            />

            <MetricCard
                icon={BarChart3}
                label={t('success_rate')}
                value={`${successRate}%`}
                subvalue={`${s.total_failed} FAILED`}
                color={successRate > 90 ? "bg-emerald-500" : "bg-red-500"}
                delay={3}
            />
        </div>
    );
}

function MetricCard({ icon: Icon, label, value, subvalue, color }: any) {
    return (
        <div
            className="group relative overflow-hidden rounded-xl border border-white/10 bg-panel/60 p-4 transition-all hover:bg-panel/80 hover:border-primary/30"
        >
            {/* Tech Decoration */}
            <div className="absolute top-0 right-0 w-16 h-16 bg-gradient-to-br from-white/5 to-transparent rounded-bl-full -mr-8 -mt-8 pointer-events-none" />
            <div className={cn("absolute bottom-0 left-0 h-[2px] w-0 group-hover:w-full transition-all duration-700 ease-out bg-gradient-to-r from-transparent via-primary to-transparent")} />

            <div className="flex items-start justify-between">
                <div>
                    <div className="text-[10px] font-bold text-text-muted/60 uppercase tracking-widest font-mono mb-1 flex items-center gap-1.5">
                        <span className={cn("w-1 h-1 rounded-full", color)}></span>
                        {label}
                    </div>
                    <div className="flex items-baseline gap-2 mt-1">
                        <div className={cn("text-2xl font-bold font-display text-text-main group-hover:text-glow tracking-tight")}>
                            {value}
                        </div>
                        {subvalue && <div className="text-xs text-text-muted font-mono">{subvalue}</div>}
                    </div>
                </div>

                <div className={cn("p-2 rounded-lg bg-white/5 text-text-muted group-hover:text-white group-hover:bg-primary/20 transition-colors duration-300 ring-1 ring-white/5")}>
                    <Icon size={18} />
                </div>
            </div>

            {/* Background Noise */}
            <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-10 pointer-events-none" />
        </div>
    );
}
