
import { useState, useEffect } from 'react';
import { Folder, HardDrive, ChevronRight } from 'lucide-react';
import { cn } from '../lib/utils';
import type { FileSystemItem, FileSystemResponse } from '../lib/types';

interface FolderPickerProps {
    onSelect: (path: string) => void;
    className?: string;
}

export function FolderPicker({ onSelect, className }: FolderPickerProps) {
    const [items, setItems] = useState<FileSystemItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [absolutePath, setAbsolutePath] = useState("");

    const fetchDir = async (path: string) => {
        setLoading(true);
        try {
            const res = await fetch(`http://localhost:8000/api/filesystem?path=${encodeURIComponent(path)}`);
            if (!res.ok) throw new Error("Failed to load dir");
            const data: FileSystemResponse = await res.json();

            setItems(data.items);
            setAbsolutePath(data.current);
            onSelect(data.current); // Notify parent of selection
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchDir(".");
    }, []);

    const handleNavigate = (path: string) => {
        fetchDir(path);
    };

    return (
        <div className={cn("flex flex-col", className)}>
            <div className="p-4 border-b border-border/50 bg-black/5 flex items-center gap-3">
                <HardDrive className="w-4 h-4 text-primary" />
                <span className="text-xs text-secondary truncate font-mono">{absolutePath || "Select a folder..."}</span>
            </div>

            <div className="flex-1 min-h-0 overflow-y-auto p-2 scrollbar-thin">
                {loading && (
                    <div className="flex items-center justify-center h-full text-secondary gap-2">
                        <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                        Loading...
                    </div>
                )}

                {!loading && items.map((item) => (
                    <div
                        key={item.path}
                        className="flex items-center gap-3 p-3 hover:bg-white/10 dark:hover:bg-white/5 rounded-lg cursor-pointer group transition-all duration-200"
                        onClick={() => handleNavigate(item.path)}
                    >
                        {item.name === ".." ? (
                            <div className="flex items-center gap-2 text-primary font-medium">
                                <ChevronRight className="w-4 h-4 rotate-180" />
                                <span>Back</span>
                            </div>
                        ) : (
                            <>
                                <Folder className="w-5 h-5 text-primary/80 group-hover:text-primary transition-colors" />
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
