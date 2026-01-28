import { useTranslation } from "../lib/language";
import { Languages } from "lucide-react";

export function Header({ title, isRunning }: { title: string, isRunning: boolean }) {
    const { language, setLanguage, t } = useTranslation();

    return (
        <header className="flex justify-between items-center bg-surface border-b border-border px-6 h-14 shrink-0 transition-all">
            <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                    <span className="text-secondary text-xs font-mono uppercase tracking-widest">Context:</span>
                    <h2 className="text-sm font-bold text-text uppercase tracking-wide">
                        {t(title as any) || title}
                    </h2>
                </div>

                {isRunning && (
                    <div className="flex items-center gap-2 px-2 py-0.5 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded text-[10px] font-mono font-bold uppercase tracking-wider">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                        {t('running')}
                    </div>
                )}
            </div>

            <div className="flex items-center gap-2">
                <button
                    onClick={() => setLanguage(language === 'en' ? 'zh' : 'en')}
                    className="p-1.5 rounded hover:bg-white/5 text-secondary hover:text-text transition-colors"
                    title="Switch Language"
                >
                    <Languages className="w-4 h-4" />
                </button>
            </div>
        </header>
    );
}
