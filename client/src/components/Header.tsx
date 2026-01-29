import { useEffect, useState } from 'react';
import { BarChart3, Database, Cpu, Moon, Sun } from 'lucide-react';
import { motion } from 'framer-motion';
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
        <header className="w-full flex items-center justify-between">
            <div className="w-full glass-panel-pro rounded-3xl border border-glass-border shadow-sm px-6 py-3 flex items-center justify-between gap-6">
                {/* Left: Logo & Title - REMOVED, now in Sidebar */}
                <div className="flex items-center gap-4 min-w-0">
                    {/* Spacer or Breadcrumb could go here */}
                    <div className="text-[10px] uppercase font-bold text-muted-foreground/60 tracking-widest mt-0.5">
                        {t(title as any) || title}
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
                <div className="flex items-center gap-4">
                    {/* Language Toggler (Animated Pill) */}
                    <div className="bg-slate-200/50 dark:bg-black/20 p-1 rounded-full flex relative">
                        {/* Sliding Background */}
                        <motion.div
                            className="absolute top-1 bottom-1 w-[34px] bg-white dark:bg-white/10 rounded-full shadow-sm z-0"
                            animate={{ x: language === 'en' ? 0 : 34 }}
                            transition={{ type: "spring", stiffness: 300, damping: 30 }}
                        />
                        {Object.keys(languageOptions).map((lang) => (
                            <button
                                key={lang}
                                onClick={() => setLanguage(lang as any)}
                                className={cn(
                                    "relative z-10 w-[34px] h-[22px] flex items-center justify-center text-[10px] font-bold transition-colors duration-300",
                                    language === lang
                                        ? "text-black dark:text-white"
                                        : "text-slate-500 dark:text-slate-400 hover:text-slate-700"
                                )}
                            >
                                {lang === 'en' ? 'EN' : 'CN'}
                            </button>
                        ))}
                    </div>

                    {/* Theme Toggler (Animated) */}
                    <button
                        onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                        className="w-9 h-9 rounded-full bg-slate-200/50 dark:bg-white/10 flex items-center justify-center text-slate-600 dark:text-white hover:bg-slate-300/50 dark:hover:bg-white/20 transition-all active:scale-95"
                    >
                        <motion.div
                            initial={false}
                            animate={{ rotate: theme === 'dark' ? 180 : 0, scale: theme === 'dark' ? 1.1 : 1 }}
                            transition={{ duration: 0.4, type: "spring" }}
                        >
                            {theme === 'dark' ? (
                                <Moon size={18} className="fill-current" />
                            ) : (
                                <Sun size={18} className="fill-current text-orange-500" />
                            )}
                        </motion.div>
                    </button>
                </div>
            </div>
        </header>
    );
}

function StatItem({ label, value, active, color, icon: Icon }: any) {
    return (
        <div className="flex flex-col items-center min-w-[80px]">
            <div className="text-xs font-bold uppercase text-muted-foreground/60 tracking-wider mb-0.5 flex items-center gap-1.5">
                {color && <div className={cn("w-1.5 h-1.5 rounded-full shadow-sm", color, active && "animate-pulse")} />}
                {label}
            </div>
            <div className="font-mono text-sm font-bold text-foreground flex items-center gap-1.5">
                {Icon && <Icon size={14} className="text-primary/70" />}
                {value}
            </div>
        </div>
    );
}
