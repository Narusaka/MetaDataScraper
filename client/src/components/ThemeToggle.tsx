
import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

export function ThemeToggle() {
    const { theme, setTheme } = useTheme();
    const [mounted, setMounted] = useState(false);

    // Avoid hydration mismatch
    useEffect(() => {
        setMounted(true);
    }, []);

    if (!mounted) return null;

    return (
        <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="relative p-2 rounded-full glass-button hover:bg-white/10 dark:hover:bg-black/20 group"
            title="Toggle Theme"
        >
            <div className="relative w-5 h-5">
                <Sun
                    className={`absolute inset-0 w-full h-full transition-all duration-500 transform ${theme === 'dark' ? 'rotate-90 opacity-0 scale-0' : 'rotate-0 opacity-100 scale-100 text-amber-500'
                        }`}
                />
                <Moon
                    className={`absolute inset-0 w-full h-full transition-all duration-500 transform ${theme === 'dark' ? 'rotate-0 opacity-100 scale-100 text-violet-400' : '-rotate-90 opacity-0 scale-0'
                        }`}
                />
            </div>
        </button>
    );
}
