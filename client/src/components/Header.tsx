import { useTranslation } from "../lib/language";
import { Languages, Activity } from "lucide-react";
import { ThemeToggle } from "./ThemeToggle";
import { motion } from "framer-motion";

export function Header({ title, isRunning }: { title: string, isRunning: boolean }) {
    const { language, setLanguage, t } = useTranslation();

    return (
        <motion.header
            initial={{ y: -20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            className="flex justify-between items-center bg-transparent h-16 shrink-0 z-30 transition-all"
        >
            <div className="flex items-center gap-6">
                <div className="flex flex-col">
                    <h2 className="text-2xl font-bold text-text-main tracking-tight font-display uppercase leading-none">
                        {t(title as any) || title}
                    </h2>
                    <span className="text-[10px] text-primary/80 font-mono tracking-[0.3em] uppercase mt-1">
                        Systems Operational
                    </span>
                </div>

                {isRunning && (
                    <div className="relative group">
                        <div className="absolute inset-0 bg-accent-success/20 blur-md rounded-full animate-pulse" />
                        <div className="relative flex items-center gap-2 px-3 py-1 bg-accent-success/10 text-accent-success border border-accent-success/20 rounded-full text-[10px] font-mono font-bold uppercase tracking-wider backdrop-blur-md">
                            <Activity size={12} className="animate-spin-slow" />
                            <span>{t('running')}</span>
                        </div>
                    </div>
                )}
            </div>

            <div className="flex items-center gap-3 bg-panel/30 border border-white/5 backdrop-blur-md px-2 py-1.5 rounded-full shadow-lg">
                <ThemeToggle />
                <div className="w-px h-4 bg-white/10" />
                <button
                    onClick={() => setLanguage(language === 'en' ? 'zh' : 'en')}
                    className="flex items-center gap-2 px-3 py-1.5 rounded-full hover:bg-white/10 text-text-muted hover:text-text-main transition-all text-xs font-bold uppercase tracking-wider group relative overflow-hidden"
                    title="Switch Language"
                >
                    <Languages className="w-3.5 h-3.5 text-primary group-hover:rotate-12 transition-transform" />
                    <span>{language === 'en' ? 'EN' : 'CN'}</span>
                </button>
            </div>
        </motion.header>
    );
}
