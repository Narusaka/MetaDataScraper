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
            className="h-screen bg-surface border-r border-border flex flex-col z-20 transition-all duration-300 relative shadow-2xl"
            style={{ width }}
        >
            {/* Header Area */}
            <div className={cn(
                "h-14 flex items-center border-b border-border transition-all overflow-hidden bg-background/50",
                isCollapsed ? "justify-center px-0 bg-primary/5" : "px-5"
            )}>
                <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded bg-primary flex items-center justify-center text-background font-black shrink-0 shadow-[0_0_15px_rgba(56,189,248,0.3)]">
                        MA
                    </div>
                    <div className={cn("transition-opacity duration-200", isCollapsed ? "hidden" : "block")}>
                        <h1 className="text-sm font-bold text-text tracking-wide uppercase">MediaAgent</h1>
                        <p className="text-[10px] text-secondary font-mono">v2.0 Console</p>
                    </div>
                </div>
            </div>

            {/* Navigation */}
            <div className="flex-1 py-4 flex flex-col gap-1 px-2">
                <p className={cn("px-3 text-[10px] font-bold text-secondary uppercase tracking-widest mb-2", isCollapsed && "hidden")}>
                    Main Modules
                </p>

                <NavItem
                    icon={<LayoutDashboard size={18} />}
                    label={t('dashboard')}
                    active={activeTab === 'dashboard'}
                    onClick={() => onTabChange('dashboard')}
                    collapsed={isCollapsed}
                />
                <NavItem
                    icon={<Activity size={18} />}
                    label={t('monitoring')}
                    active={activeTab === 'monitoring'}
                    onClick={() => onTabChange('monitoring')}
                    collapsed={isCollapsed}
                />

                <div className="my-4 border-t border-border/50 mx-2" />

                <p className={cn("px-3 text-[10px] font-bold text-secondary uppercase tracking-widest mb-2", isCollapsed && "hidden")}>
                    System
                </p>

                <NavItem
                    icon={<Settings size={18} />}
                    label={t('settings')}
                    active={activeTab === 'settings'}
                    onClick={() => onTabChange('settings')}
                    collapsed={isCollapsed}
                />
            </div>

            {/* Footer / Status Summary */}
            <div className="p-2 border-t border-border bg-background/50">
                <div className={cn(
                    "rounded bg-background border border-border p-2 flex items-center gap-3",
                    isCollapsed ? "justify-center aspect-square p-0 bg-transparent border-none" : ""
                )}>
                    <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse shrink-0 shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
                    {!isCollapsed && <span className="text-xs font-mono text-secondary">System Online</span>}
                </div>
            </div>

            {/* Resizer Handle */}
            <div
                onMouseDown={startResizing}
                onDoubleClick={() => setWidth(260)}
                className={cn(
                    "absolute top-0 right-[-1px] bottom-0 w-1 cursor-col-resize z-50 transition-colors hover:bg-primary",
                    isResizing && "bg-primary"
                )}
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
        <button
            onClick={onClick}
            className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-md transition-all duration-150 group relative w-full text-left",
                active
                    ? "bg-primary/10 text-primary border border-primary/20 shadow-inner"
                    : "text-secondary hover:bg-white/5 hover:text-text",
                collapsed && "justify-center px-0 aspect-square"
            )}
            title={collapsed ? label : undefined}
        >
            <div className={cn("shrink-0 transition-transform group-hover:scale-110", active && "text-primary")}>
                {icon}
            </div>
            {!collapsed && (
                <span className="text-xs font-medium tracking-wide truncated">
                    {label}
                </span>
            )}
            {active && !collapsed && (
                <div className="absolute right-2 w-1.5 h-1.5 rounded-full bg-primary shadow-[0_0_5px_currentColor]" />
            )}
        </button>
    );
}
