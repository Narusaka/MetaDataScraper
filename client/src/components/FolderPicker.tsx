
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
    const [error, setError] = useState<string | null>(null);
    const [inputValue, setInputValue] = useState(initialPath || "");
    const [recentPaths, setRecentPaths] = useState<string[]>([]);

    useEffect(() => {
        let history: string[] = [];
        try {
            history = JSON.parse(localStorage.getItem('recent_paths') || '[]');
            setRecentPaths(history);
        } catch (e) { }

        if (initialPath) {
            initLoad(initialPath);
        } else if (history.length === 0) {
            fetchDir(".");
        }
    }, []);

    const getParentPath = (path: string) => {
        if (!path || path === "/") return path;
        const clean = path.endsWith('/') && path.length > 1 ? path.slice(0, -1) : path;
        const lastSlash = clean.lastIndexOf('/');
        if (lastSlash <= 0) return "/";
        return clean.substring(0, lastSlash);
    };

    // Initial load with recursive parent fallback
    const initLoad = async (startPath: string) => {
        setLoading(true);
        setError(null);
        let current = startPath;
        let attempts = 0;
        const maxAttempts = 10; // Prevent infinite loops

        while (current && attempts < maxAttempts) {
            try {
                const res = await fetch(`http://localhost:8000/api/filesystem?path=${encodeURIComponent(current)}`);
                if (res.ok) {
                    const data: FileSystemResponse = await res.json();
                    setItems(data.items);
                    setInputValue(data.current);
                    onSelect(data.current);
                    setLoading(false);
                    return; // Success!
                }
            } catch (e) {
                // Ignore network errors during fallback search, just try next
            }

            // Failed, try parent
            const parent = getParentPath(current);
            if (!parent || parent === current) break; // Reached root or stuck
            current = parent;
            attempts++;
        }

        // If we get here, all attempts failed
        setLoading(false);
        // If we get here, all attempts failed
        setLoading(false);
        // Do NOT clear input value, so user can correct it or keep the custom path
        setInputValue(startPath || "");
        setError("Failed to load path or any parent directories.");
    };

    const fetchDir = async (path: string) => {
        if (!path) return;
        setLoading(true);
        setError(null);
        try {
            const res = await fetch(`http://localhost:8000/api/filesystem?path=${encodeURIComponent(path)}`);
            if (!res.ok) throw new Error(`Failed to access directory: ${path}`);
            const data: FileSystemResponse = await res.json();

            setItems(data.items);
            setInputValue(data.current);
            onSelect(data.current);
        } catch (e: any) {
            console.error(e);
            setError(e.message || "Unknown error occurred");
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
                    onChange={(e) => {
                        setInputValue(e.target.value);
                        onSelect(e.target.value);
                    }}
                    onKeyDown={handleKeyDown}
                    placeholder={t('select_folder')}
                    className="flex-1 bg-muted/50 border border-border/30 hover:border-primary/50 focus:border-primary focus:ring-1 focus:ring-primary/50 rounded-md px-3 py-1.5 text-xs text-foreground font-mono outline-none transition-all placeholder:text-muted"
                />
            </div>

            <div className="flex-1 min-h-0 overflow-y-auto p-2 scrollbar-thin">
                {error && (
                    <div className="mx-2 my-2 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs flex items-center gap-2">
                        <div className="w-1.5 h-1.5 rounded-full bg-red-500 shrink-0" />
                        {error}
                        <button onClick={() => fetchDir(".")} className="ml-auto underline hover:text-red-300">
                            Go Home
                        </button>
                    </div>
                )}

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
