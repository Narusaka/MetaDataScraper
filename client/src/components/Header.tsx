import { useEffect, useState } from 'react';
import { BarChart3, Database, Cpu, Moon, Sun, MonitorCheck, Loader2 } from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '../lib/utils';
import { useTranslation, languageOptions } from '../lib/language';
import { useTheme } from 'next-themes';
import { toast } from 'sonner';

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
    const [isChecking, setIsChecking] = useState(false);

    const handleConnectivityTest = async () => {
        if (isChecking) return;
        setIsChecking(true);
        const toastId = toast.loading('Checking connectivity...');

        try {
            const res = await fetch('http://localhost:8000/api/test_connectivity');
            const data = await res.json();

            // Format result for toast
            const tmdbOk = data.tmdb?.status === 'ok';
            const tavilyOk = data.tavily?.status === 'ok';

            const msg = (
                <div className="text-xs space-y-1">
                    <div className="font-bold mb-2 text-sm">System Connectivity</div>
                    <div className={cn("flex items-center gap-2", tmdbOk ? "text-green-500" : "text-red-500")}>
                        <div className={cn("w-2 h-2 rounded-full", tmdbOk ? "bg-green-500" : "bg-red-500")} />
                        TMDB: {data.tmdb?.message || 'OK'}
                    </div>
                    <div className={cn("flex items-center gap-2", tavilyOk ? "text-green-500" : "text-amber-500")}>
                        <div className={cn("w-2 h-2 rounded-full", tavilyOk ? "bg-green-500" : "bg-amber-500")} />
                        Tavily: {data.tavily?.message || 'OK'}
                    </div>
                </div>
            );

            toast.dismiss(toastId);
            if (tmdbOk && tavilyOk) toast.success(msg, { duration: 3000 });
            else if (tmdbOk) toast.warning(msg, { duration: 5000 }); // Partial success
            else toast.error(msg, { duration: 5000 });

        } catch (e) {
            toast.dismiss(toastId);
            toast.error("Failed to connect to backend server.");
        } finally {
            setIsChecking(false);
        }
    };

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
                    <div className="bg-[var(--bg-toggle-wrapper)] p-1 rounded-full flex relative">
                        {/* Sliding Background */}
                        <motion.div
                            className="absolute top-1 bottom-1 w-[34px] bg-[var(--bg-toggle-pill)] rounded-full shadow-sm z-0"
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
                                        ? "text-[var(--text-toggle-active)]"
                                        : "text-[var(--text-toggle-inactive)] hover:text-[var(--text-toggle-active)]"
                                )}
                            >
                                {lang === 'en' ? 'EN' : 'CN'}
                            </button>
                        ))}
                    </div>

                    {/* Connectivity Test Button (Animated) */}
                    <button
                        onClick={handleConnectivityTest}
                        disabled={isChecking}
                        className={cn(
                            "w-9 h-9 rounded-full bg-[var(--bg-toggle-wrapper)] flex items-center justify-center transition-all active:scale-95",
                            isChecking ? "cursor-wait opacity-80" : "text-[var(--text-toggle-inactive)] hover:text-emerald-500 hover:bg-[var(--bg-button-secondary-active)]"
                        )}
                        title="Test Server Connectivity"
                    >
                        {isChecking ? (
                            <Loader2 size={18} className="animate-spin text-primary" />
                        ) : (
                            <MonitorCheck size={18} className="fill-current" />
                        )}
                    </button>

                    {/* Theme Toggler (Animated) */}
                    <button
                        onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                        className="w-9 h-9 rounded-full bg-[var(--bg-toggle-wrapper)] flex items-center justify-center text-[var(--text-toggle-inactive)] hover:bg-[var(--bg-button-secondary-active)] transition-all active:scale-95"
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
