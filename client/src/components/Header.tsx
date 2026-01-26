
import { ThemeToggle } from "./ThemeToggle";
import { useTranslation } from "../lib/language";
import { Languages } from "lucide-react";

export function Header({ title, isRunning }: { title: string, isRunning: boolean }) {
    const { language, setLanguage, t } = useTranslation();

    return (
        <header className="flex justify-between items-center glass-panel px-6 py-4 rounded-xl z-10 sticky top-0 shrink-0 mb-6">
            <div className="flex items-center gap-4">
                <h2 className="text-2xl font-bold bg-gradient-to-r from-primary to-violet-400 bg-clip-text text-transparent capitalize">
                    {t(title as any) || title}
                </h2>
                {isRunning && (
                    <div className="flex items-center gap-2 px-3 py-1 bg-green-500/20 text-green-400 border border-green-500/30 rounded-full text-xs font-medium animate-pulse">
                        <span className="w-2 h-2 rounded-full bg-green-500 shadow-[0_0_10px_#22c55e]"></span>
                        {t('running')}
                    </div>
                )}
            </div>

            <div className="flex items-center gap-3">
                <button
                    onClick={() => setLanguage(language === 'en' ? 'zh' : 'en')}
                    className="p-2 glass-button rounded-full hover:bg-white/10"
                    title="Switch Language"
                >
                    <Languages className="w-5 h-5 text-secondary" />
                </button>
                <ThemeToggle />
            </div>
        </header>
    );
}
