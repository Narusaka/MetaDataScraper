import { useTranslation } from "../lib/language";
import { Languages } from "lucide-react";
import { ThemeToggle } from "./ThemeToggle";

export function Header({ title, isRunning }: { title: string, isRunning: boolean }) {
    const { language, setLanguage, t } = useTranslation();

    return (
        <header className="flex justify-between items-center bg-panel/50 backdrop-blur-sm border-b border-border-light h-16 shrink-0 px-6 sticky top-0 z-30 transition-all">
            <div className="flex items-center gap-4">
                <h2 className="text-xl font-bold text-text-main tracking-tight capitalize">
                    {t(title as any) || title}
                </h2>

                {isRunning && (
                    <div className="flex items-center gap-2 px-2.5 py-0.5 bg-accent-success/10 text-accent-success border border-accent-success/20 rounded-full text-[10px] font-mono font-bold uppercase tracking-wider">
                        <span className="w-1.5 h-1.5 rounded-full bg-accent-success animate-pulse"></span>
                        {t('running')}
                    </div>
                )}
            </div>

            <div className="flex items-center gap-1">
                <ThemeToggle />
                <div className="w-px h-6 bg-border-light mx-2" />
                <button
                    onClick={() => setLanguage(language === 'en' ? 'zh' : 'en')}
                    className="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-surface text-text-muted hover:text-text-main transition-all text-sm font-medium"
                    title="Switch Language"
                >
                    <Languages className="w-4 h-4" />
                    <span>{language === 'en' ? 'English' : '中文'}</span>
                </button>
            </div>
        </header>
    );
}
