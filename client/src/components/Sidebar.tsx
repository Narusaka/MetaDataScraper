import { useState, useEffect, useCallback } from 'react';
import { LayoutDashboard, Settings, Activity } from 'lucide-react';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/language';

interface SidebarProps {
    activeTab: string;
    onTabChange: (tab: string) => void;
}

export function Sidebar({ activeTab, onTabChange }: SidebarProps) {
    const { t } = useTranslation();
    const [width, setWidth] = useState(260);
    const [isResizing, setIsResizing] = useState(false);

    // Auto-collapse if width is small
    const isCollapsed = width < 180;

    const startResizing = useCallback(() => setIsResizing(true), []);
    const stopResizing = useCallback(() => setIsResizing(false), []);

    const resize = useCallback((mouseMoveEvent: MouseEvent) => {
        if (isResizing) {
            // Limits: Min 80px (icon only), Max 600px
            const newWidth = Math.max(80, Math.min(mouseMoveEvent.clientX, 600));
            setWidth(newWidth);
        }
    }, [isResizing]);

    useEffect(() => {
        if (isResizing) {
            window.addEventListener("mousemove", resize);
            window.addEventListener("mouseup", stopResizing);
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
        } else {
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        }

        return () => {
            window.removeEventListener("mousemove", resize);
            window.removeEventListener("mouseup", stopResizing);
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        };
    }, [isResizing, resize, stopResizing]);

    return (
        <div
            className="glass-panel border-y-0 border-l-0 border-r border-border/30 flex flex-col py-6 gap-2 z-20 h-screen sticky top-0 shrink-0 relative transition-none"
            style={{ width }}
        >
            {/* Header */}
            <div className={cn(
                "px-6 mb-8 transition-all duration-200 overflow-hidden whitespace-nowrap",
                isCollapsed ? "opacity-0 h-0 p-0 mb-4" : "opacity-100"
            )}>
                <h1 className="text-xl font-bold bg-gradient-to-r from-primary to-violet-400 bg-clip-text text-transparent">
                    MediaAgent
                </h1>
                <p className="text-xs text-secondary">Metadata Scraper</p>
            </div>

            <NavItem
                icon={<LayoutDashboard />}
                label={t('dashboard')}
                active={activeTab === 'dashboard'}
                onClick={() => onTabChange('dashboard')}
                collapsed={isCollapsed}
            />
            <NavItem
                icon={<Activity />}
                label={t('monitoring')}
                active={activeTab === 'monitoring'}
                onClick={() => onTabChange('monitoring')}
                collapsed={isCollapsed}
            />

            <div className="flex-1" />

            <NavItem
                icon={<Settings />}
                label={t('settings')}
                active={activeTab === 'settings'}
                onClick={() => onTabChange('settings')}
                collapsed={isCollapsed}
            />

            {/* Resizer Handle */}
            <div
                onMouseDown={startResizing}
                onDoubleClick={() => setWidth(260)}
                className={cn(
                    "absolute top-0 right-0 bottom-0 w-1.5 cursor-col-resize z-50 transition-colors hover:bg-primary/50",
                    isResizing && "bg-primary"
                )}
                title="Drag to resize, double click to reset"
            />
        </div>
    );
}

interface NavItemProps {
    icon: React.ReactNode;
    label: string;
    active?: boolean;
    onClick?: () => void;
    collapsed?: boolean;
}

function NavItem({ icon, label, active = false, onClick, collapsed = false }: NavItemProps) {
    return (
        <div
            onClick={onClick}
            className={cn(
                "flex items-center gap-3 px-6 py-3 mx-2 rounded-lg cursor-pointer transition-all duration-300 overflow-hidden whitespace-nowrap",
                active
                    ? "bg-primary/20 text-primary border border-primary/20"
                    : "text-secondary hover:bg-white/10 dark:hover:bg-white/5 hover:text-primary",
                collapsed && "justify-center px-2"
            )}>
            <div className="shrink-0 flex items-center justify-center">
                {icon}
            </div>
            <span className={cn(
                "font-medium transition-opacity duration-200",
                collapsed ? "opacity-0 w-0 hidden" : "opacity-100"
            )}>
                {label}
            </span>
        </div>
    );
}
