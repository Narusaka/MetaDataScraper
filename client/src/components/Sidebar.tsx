import { useState } from 'react';
import { LayoutDashboard, Settings, Activity, ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/language';

interface SidebarProps {
    activeTab: string;
    onTabChange: (tab: string) => void;
    mobileOpen?: boolean;
    onMobileClose?: () => void;
}

export function Sidebar({ activeTab, onTabChange, mobileOpen = false, onMobileClose }: SidebarProps) {
    const { t } = useTranslation();
    const [collapsed, setCollapsed] = useState(false);

    const NavItem = ({ icon: Icon, label, id }: { icon: any, label: string, id: string }) => {
        const isActive = activeTab === id;
        return (
            <button
                onClick={() => {
                    onTabChange(id);
                    if (window.innerWidth < 768) onMobileClose?.();
                }}
                className={cn(
                    "group flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-200 relative mb-1",
                    isActive
                        ? "bg-primary text-white shadow-lg shadow-primary/25"
                        : "text-text-muted hover:bg-surface hover:text-text-main",
                    collapsed ? "justify-center px-0 w-12 h-12 mx-auto" : "w-full"
                )}
                title={collapsed ? label : undefined}
            >
                <Icon size={20} className={cn("shrink-0 transition-transform", !isActive && "group-hover:scale-110")} />
                {!collapsed && (
                    <span className="font-medium text-sm tracking-wide">{label}</span>
                )}
                {/* Active Indicator for collapsed state */}
                {isActive && collapsed && (
                    <div className="absolute right-0 top-1/2 -translate-y-1/2 w-1 h-8 bg-white rounded-l opacity-20" />
                )}
            </button>
        )
    };

    return (
        <>
            {/* Mobile Overlay */}
            <div
                className={cn(
                    "fixed inset-0 bg-black/60 backdrop-blur-sm z-40 md:hidden transition-opacity duration-300",
                    mobileOpen ? "opacity-100" : "opacity-0 pointer-events-none"
                )}
                onClick={onMobileClose}
            />

            {/* Sidebar Container */}
            <aside
                className={cn(
                    "fixed md:relative z-50 h-full bg-panel/80 backdrop-blur-xl border-r border-border-light flex flex-col transition-all duration-300 ease-in-out shadow-2xl md:shadow-none",
                    collapsed ? "w-20" : "w-64",
                    mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
                )}
            >
                {/* Header */}
                <div className="h-16 flex items-center px-4 border-b border-border-light/50">
                    <div className={cn("flex items-center gap-3 overflow-hidden", collapsed ? "justify-center w-full" : "")}>
                        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-primary to-blue-600 flex items-center justify-center text-white font-bold text-lg shrink-0 shadow-lg shadow-primary/20">
                            M
                        </div>
                        {!collapsed && (
                            <div className="flex flex-col">
                                <span className="font-bold text-text-main leading-tight">MediaAgent</span>
                                <span className="text-[10px] text-text-muted font-mono bg-surface px-1.5 py-0.5 rounded-full w-fit">v2.0 PRO</span>
                            </div>
                        )}
                    </div>
                </div>

                {/* Nav Items */}
                <div className="flex-1 py-6 px-3 flex flex-col gap-2 overflow-y-auto">
                    <div className={cn("px-3 text-[10px] font-bold text-text-muted/60 uppercase tracking-widest mb-1", collapsed && "hidden")}>
                        MODULES
                    </div>
                    <NavItem icon={LayoutDashboard} label={t('dashboard')} id="dashboard" />
                    <NavItem icon={Activity} label={t('monitoring')} id="monitoring" />

                    <div className="my-4 border-t border-border-light/50 mx-2" />

                    <div className={cn("px-3 text-[10px] font-bold text-text-muted/60 uppercase tracking-widest mb-1", collapsed && "hidden")}>
                        SYSTEM
                    </div>
                    <NavItem icon={Settings} label={t('settings')} id="settings" />
                </div>

                {/* Footer / Toggle */}
                <div className="p-4 border-t border-border-light/50 flex flex-col gap-2">
                    <button
                        onClick={() => setCollapsed(!collapsed)}
                        className={cn(
                            "hidden md:flex items-center justify-center w-full h-9 rounded-lg hover:bg-surface text-text-muted transition-colors",
                            collapsed && "aspect-square"
                        )}
                    >
                        {collapsed ? <ChevronRight size={18} /> : <div className="flex items-center gap-2 text-xs font-medium"><ChevronLeft size={16} /> <span className="uppercase">Collapse</span></div>}
                    </button>

                    {!collapsed && (
                        <div className="text-[10px] text-center text-text-muted/40 font-mono py-2">
                            SYSTEM ONLINE • STABLE
                        </div>
                    )}
                </div>
            </aside>
        </>
    );
}
