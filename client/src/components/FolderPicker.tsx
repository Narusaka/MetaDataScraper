
import { useCallback, useEffect, useState } from 'react';
import { Folder, HardDrive, ChevronRight, Clock } from 'lucide-react';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/languageContext';
import type { FileSystemItem, FileSystemResponse } from '../lib/types';
import { apiJson } from '../lib/api';

interface FolderPickerProps {
    onSelect: (path: string) => void;
    className?: string;
    initialPath?: string;
}

const getParentPath = (path: string) => {
    if (!path || path === "/") return path;
    const clean = path.endsWith('/') && path.length > 1 ? path.slice(0, -1) : path;
    const lastSlash = clean.lastIndexOf('/');
    if (lastSlash <= 0) return "/";
    return clean.substring(0, lastSlash);
};

export function FolderPicker({ onSelect, className, initialPath }: FolderPickerProps) {
    const { t } = useTranslation();
    const [items, setItems] = useState<FileSystemItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [inputValue, setInputValue] = useState(initialPath || "");
    const [recentPaths, setRecentPaths] = useState<string[]>([]);

    const fetchDir = useCallback(async (path: string) => {
        if (!path) return;
        setLoading(true);
        setError(null);
        try {
            const data = await apiJson<FileSystemResponse>(
                `/api/filesystem?path=${encodeURIComponent(path)}`,
                undefined,
                `Failed to access directory: ${path}`,
            );

            setItems(data.items);
            setInputValue(data.current);
            onSelect(data.current);
        } catch (error: unknown) {
            console.error(error);
            setError(error instanceof Error ? error.message : "Unknown error occurred");
        } finally {
            setLoading(false);
        }
    }, [onSelect]);

    // Initial load with recursive parent fallback
    const initLoad = useCallback(async (startPath: string) => {
        setLoading(true);
        setError(null);
        let current = startPath;
        let attempts = 0;
        const maxAttempts = 10; // Prevent infinite loops

        while (current && attempts < maxAttempts) {
            try {
                const data = await apiJson<FileSystemResponse>(
                    `/api/filesystem?path=${encodeURIComponent(current)}`,
                    undefined,
                    `Failed to access directory: ${current}`,
                );
                setItems(data.items);
                setInputValue(data.current);
                onSelect(data.current);
                setLoading(false);
                return; // Success!
            } catch (error) {
                console.warn("Directory fallback check failed", error);
            }

            // Failed, try parent
            const parent = getParentPath(current);
            if (!parent || parent === current) break; // Reached root or stuck
            current = parent;
            attempts++;
        }

        // If we get here, all attempts failed
        setLoading(false);
        // Do NOT clear input value, so user can correct it or keep the custom path
        setInputValue(startPath || "");
        setError("Failed to load path or any parent directories.");
    }, [onSelect]);

    useEffect(() => {
        let history: string[] = [];
        try {
            const parsed = JSON.parse(localStorage.getItem('recent_paths') || '[]');
            history = Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : [];
        } catch (error) {
            console.warn("Could not load recent paths", error);
        }

        setRecentPaths(history);
        if (initialPath) {
            initLoad(initialPath);
        } else if (history.length === 0) {
            fetchDir(".");
        }
    }, [fetchDir, initLoad, initialPath]);

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
        <div className={cn("flex flex-col h-full", className)}>
            {/* Top Bar: Path Input (Target-style) */}
            <div className="shrink-0 p-6 pb-2">
                <div className="flex items-center gap-3 bg-[var(--bg-input-target)] rounded-2xl px-4 py-2 transition-all focus-within:ring-2 focus-within:ring-primary/20">
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
                        className="flex-1 bg-transparent border-none text-sm text-foreground font-mono outline-none placeholder:text-muted/50"
                    />
                </div>
            </div>

            {/* Folder List */}
            <div className="flex-1 min-h-0 overflow-y-auto px-4 pb-4 scrollbar-thin">
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
                    <div className="flex items-center justify-center h-full text-muted-foreground gap-2">
                        <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                        <span className="text-xs uppercase tracking-widest">{t('loading')}</span>
                    </div>
                )}

                {!loading && showRecent && (
                    <div className="space-y-1 mt-2">
                        <div className="px-3 py-2 text-[10px] font-bold uppercase tracking-widest text-muted-foreground/60">
                            Recent Paths
                        </div>
                        {recentPaths.map((path) => (
                            <div
                                key={path}
                                className="flex items-center gap-3 p-3 hover:bg-[var(--bg-toggle-wrapper)] rounded-xl cursor-pointer group transition-all duration-200"
                                onClick={() => handleNavigate(path)}
                            >
                                <Clock className="w-4 h-4 text-primary/60 group-hover:text-primary transition-colors shrink-0" />
                                <span className="text-sm text-muted-foreground group-hover:text-foreground transition-colors truncate font-mono opacity-80">
                                    {path}
                                </span>
                            </div>
                        ))}
                    </div>
                )}

                {!loading && !showRecent && (
                    <div className="mt-2 space-y-0.5">
                        {items.map((item) => (
                            <div
                                key={item.path}
                                className="flex items-center gap-3 p-3 hover:bg-[var(--bg-toggle-wrapper)] rounded-xl cursor-pointer group transition-all duration-200"
                                onClick={() => handleNavigate(item.path)}
                            >
                                {item.name === ".." ? (
                                    <div className="flex items-center gap-2 text-primary font-bold text-sm">
                                        <ChevronRight className="w-4 h-4 rotate-180" />
                                        <span>{t('back')}</span>
                                    </div>
                                ) : (
                                    <>
                                        <Folder className={cn(
                                            "w-5 h-5 transition-colors shrink-0",
                                            item.name.startsWith('.') ? "text-muted-foreground/40" : "text-blue-500/80 group-hover:text-blue-400"
                                        )} />
                                        <span className="text-sm text-muted-foreground group-hover:text-foreground transition-colors truncate font-medium">
                                            {item.name}
                                        </span>
                                    </>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
