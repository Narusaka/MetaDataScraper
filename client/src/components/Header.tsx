import { useEffect, useState } from 'react';
import { BarChart3, Database, Cpu, Moon, Sun } from 'lucide-react';
import { cn } from '../lib/utils';
import { useTranslation, languageOptions } from '../lib/language';
import { useTheme } from 'next-themes';

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

export function Header({ title }: { title: string, isRunning?: boolean }) { // Keep optional isRunning in type just in case but remove from destructure if unused or remove entirely.
    const { t, language, setLanguage } = useTranslation();
    const { theme, setTheme } = useTheme();
    const [stats, setStats] = useState<SystemStats | null>(null);

    // Poll for stats
    useEffect(() => {
        const fetchStats = async () => {
            // In a real app we might use react-query or swr, keeping it simple here
            try {
                const res = await fetch('http://localhost:8000/api/status');
                // If connecting to generic stats, make sure the endpoint returns SystemStats structure
                if (res.ok) setStats(await res.json());
            } catch (e) { }
        };
        fetchStats();
        const interval = setInterval(fetchStats, 2000);
        return () => clearInterval(interval);
    }, []);

    const s = stats?.stats || { total_media: 0, total_success: 0, total_failed: 0 };
    const successRate = s.total_media ? Math.round((s.total_success / s.total_media) * 100) : 100;

    return (
        <header className="w-full flex items-center justify-between gap-6 px-0 py-2">
            {/* Left: Logo & Title */}
            <div className="flex items-center gap-4 min-w-0">
                <div className="flex items-center gap-3">
                    {/* Logo / Brand */}
                    <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-primary to-blue-500 shadow-lg shadow-primary/20 flex items-center justify-center text-white font-bold text-lg select-none">
                        M
                    </div>
                    <div className="flex flex-col justify-center">
                        <div className="font-bold text-lg leading-none tracking-tight text-foreground">
                            Media<span className="text-primary">Agent</span>
                        </div>
                        <div className="text-[10px] uppercase font-bold text-muted-foreground/60 tracking-widest mt-0.5">
                            {t(title as any) || title}
                        </div>
                    </div>
                </div>
            </div>

            {/* Middle: System Stats (Collapsed on mobile, expanded on desktop) */}
            <div className="hidden lg:flex flex-1 items-center justify-center gap-8">
                <StatItem
                    label={t('system_status')}
                    value={stats?.running ? t('status_online') : t('status_standby')}
                    active={stats?.running}
                    color={stats?.running ? "bg-emerald-500" : "bg-amber-500"}
                />
                <div className="w-px h-8 bg-border" />
                <StatItem
                    label={t('threads')}
                    value={`${stats?.workers || '--'}`}
                    icon={Cpu}
                />
                <div className="w-px h-8 bg-border" />
                <StatItem
                    label={t('processed')}
                    value={`${s.total_media} ${t('items')}`}
                    icon={Database}
                />
                {s.total_media > 0 && (
                    <>
                        <div className="w-px h-8 bg-border" />
                        <StatItem
                            label={t('success_rate')}
                            value={`${successRate}%`}
                            active={successRate > 90}
                            color={successRate > 90 ? "bg-emerald-500" : "bg-red-500"}
                            icon={BarChart3}
                        />
                    </>
                )}
            </div>

            {/* Right: Actions (Theme, Lang) */}
            <div className="flex items-center gap-2">
                {/* Language Toggler */}
                <div className="bg-slate-100 dark:bg-surface rounded-full p-1 border border-border flex items-center gap-1">
                    {Object.keys(languageOptions).map((lang) => (
                        <button
                            key={lang}
                            onClick={() => setLanguage(lang as any)}
                            className={cn(
                                "text-[10px] font-bold px-3 py-1.5 rounded-full transition-all uppercase",
                                language === lang
                                    ? "bg-primary text-white shadow-md shadow-primary/30 transform scale-105"
                                    : "text-slate-500 dark:text-muted hover:text-slate-900 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5"
                            )}
                        >
                            {lang === 'en' ? 'EN' : 'CN'}
                        </button>
                    ))}
                </div>

                {/* Theme Toggler */}
                <button
                    onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                    className="p-2.5 rounded-full bg-slate-100 dark:bg-surface border border-border text-slate-500 dark:text-muted hover:text-primary hover:bg-slate-200 dark:hover:bg-white/5 transition-all"
                    title={theme === 'dark' ? "Switch to Light Mode" : "Switch to Dark Mode"}
                >
                    {theme === 'dark' ? <Moon size={18} /> : <Sun size={18} />}
                </button>
            </div>
        </header>
    );
}

function StatItem({ label, value, active, color, icon: Icon }: any) {
    return (
        <div className="flex flex-col items-center min-w-[80px]">
            <div className="text-[9px] font-bold uppercase text-muted-foreground/60 tracking-wider mb-0.5 flex items-center gap-1.5">
                {color && <div className={cn("w-1.5 h-1.5 rounded-full shadow-sm", color, active && "animate-pulse")} />}
                {label}
            </div>
            <div className="font-mono text-xs font-bold text-foreground flex items-center gap-1.5">
                {Icon && <Icon size={12} className="text-primary/70" />}
                {value}
            </div>
        </div>
    );
}
