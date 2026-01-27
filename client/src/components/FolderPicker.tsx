
import { useState, useEffect } from 'react';
import { Folder, HardDrive, ChevronRight, Clock } from 'lucide-react';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/language';
import type { FileSystemItem, FileSystemResponse } from '../lib/types';

interface FolderPickerProps {
    onSelect: (path: string) => void;
    className?: string;
    initialPath?: string;
}

export function FolderPicker({ onSelect, className, initialPath }: FolderPickerProps) {
    const { t } = useTranslation();
    const [items, setItems] = useState<FileSystemItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [inputValue, setInputValue] = useState(initialPath || "");
    const [recentPaths, setRecentPaths] = useState<string[]>([]);

    useEffect(() => {
        let history: string[] = [];
        try {
            history = JSON.parse(localStorage.getItem('recent_paths') || '[]');
            setRecentPaths(history);
        } catch (e) { }

        if (initialPath) {
            fetchDir(initialPath);
        } else if (history.length === 0) {
            // If no saved path and no history, load root
            fetchDir(".");
        }
        // Else: leave inputValue empty to show recent paths
    }, []);

    const fetchDir = async (path: string) => {
        if (!path) return; // Don't fetch empty path
        setLoading(true);
        try {
            const res = await fetch(`http://localhost:8000/api/filesystem?path=${encodeURIComponent(path)}`);
            if (!res.ok) throw new Error("Failed to load dir");
            const data: FileSystemResponse = await res.json();

            setItems(data.items);
            setInputValue(data.current); // Sync input with loaded path
            // localStorage.setItem('last_path', data.current); // Removed: Parent manages persistence
            onSelect(data.current); // Notify parent of selection
        } catch (e) {
            console.error(e);
            // If failed to load a specific path (e.g. cached path deleted), fallback to root
            if (path !== ".") fetchDir(".");
        } finally {
            setLoading(false);
        }
    };

    const handleNavigate = (path: string) => {
        fetchDir(path);
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'Enter') {
            fetchDir(inputValue);
        }
    };

    const showRecent = !inputValue && recentPaths.length > 0;

    return (
        <div className={cn("flex flex-col", className)}>
            <div className="p-4 border-b border-border/50 bg-black/5 flex items-center gap-3">
                <HardDrive className="w-5 h-5 text-primary shrink-0" />
                <input
                    type="text"
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={t('select_folder')}
                    className="flex-1 bg-muted/50 border border-border/30 hover:border-primary/50 focus:border-primary focus:ring-1 focus:ring-primary/50 rounded-md px-3 py-1.5 text-xs text-foreground font-mono outline-none transition-all placeholder:text-muted"
                />
            </div>

            <div className="flex-1 min-h-0 overflow-y-auto p-2 scrollbar-thin">
                {loading && (
                    <div className="flex items-center justify-center h-full text-secondary gap-2">
                        <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                        {t('loading')}
                    </div>
                )}

                {!loading && showRecent && (
                    <div className="space-y-1">
                        <div className="px-3 py-2 text-[10px] font-bold uppercase tracking-widest text-muted-foreground opacity-70">
                            Recent Paths
                        </div>
                        {recentPaths.map((path) => (
                            <div
                                key={path}
                                className="flex items-center gap-3 p-3 hover:bg-white/10 dark:hover:bg-white/5 rounded-lg cursor-pointer group transition-all duration-200"
                                onClick={() => handleNavigate(path)}
                            >
                                <Clock className="w-4 h-4 text-primary/60 group-hover:text-primary transition-colors shrink-0" />
                                <span className="text-sm text-secondary group-hover:text-foreground transition-colors truncate font-mono opacity-80">
                                    {path}
                                </span>
                            </div>
                        ))}
                    </div>
                )}

                {!loading && !showRecent && items.map((item) => (
                    <div
                        key={item.path}
                        className="flex items-center gap-3 p-3 hover:bg-white/10 dark:hover:bg-white/5 rounded-lg cursor-pointer group transition-all duration-200"
                        onClick={() => handleNavigate(item.path)}
                    >
                        {item.name === ".." ? (
                            <div className="flex items-center gap-2 text-primary font-medium">
                                <ChevronRight className="w-4 h-4 rotate-180" />
                                <span>{t('back')}</span>
                            </div>
                        ) : (
                            <>
                                <Folder className="w-5 h-5 text-primary/80 group-hover:text-primary transition-colors shrink-0" />
                                <span className="text-sm text-secondary group-hover:text-foreground transition-colors truncate">
                                    {item.name}
                                </span>
                            </>
                        )}
                    </div>
                ))}
            </div>
        </div>
    );
}
