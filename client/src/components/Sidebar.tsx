import { useState } from 'react';
import { LayoutDashboard, Settings, Activity, ChevronLeft, ChevronRight, Hexagon, Command, Cpu } from 'lucide-react';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/language';
import { motion, AnimatePresence } from 'framer-motion';

interface SidebarProps {
    activeTab: string;
    onTabChange: (tab: string) => void;
    mobileOpen?: boolean;
    onMobileClose?: () => void;
}

export function Sidebar({ activeTab, onTabChange, mobileOpen = false, onMobileClose }: SidebarProps) {
    const { t } = useTranslation();
    const [collapsed, setCollapsed] = useState(true);

    const NavItem = ({ icon: Icon, label, id }: { icon: any, label: string, id: string }) => {
        const isActive = activeTab === id;

        return (
            <motion.button
                layout
                onClick={() => {
                    onTabChange(id);
                    if (window.innerWidth < 768) onMobileClose?.();
                }}
                className={cn(
                    "group relative flex items-center gap-4 px-3 py-3 rounded-xl transition-all duration-300 overflow-hidden",
                    isActive
                        ? "text-primary bg-primary/10 shadow-[0_0_20px_rgba(59,130,246,0.15)] border border-primary/20"
                        : "text-text-muted hover:text-text-main hover:bg-white/5",
                    collapsed ? "justify-center w-12 h-12 mx-auto px-0" : "w-full"
                )}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
            >
                {/* Active Indicator Line (Left) */}
                {isActive && (
                    <motion.div
                        layoutId="activeIndicator"
                        className="absolute left-0 top-2 bottom-2 w-1 bg-primary rounded-r-full shadow-[0_0_10px_var(--primary)]"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                    />
                )}

                <div className="relative z-10 flex items-center gap-4">
                    <Icon
                        size={20}
                        className={cn(
                            "shrink-0 transition-colors duration-300",
                            isActive ? "text-primary drop-shadow-[0_0_8px_rgba(59,130,246,0.5)]" : "group-hover:text-text-main"
                        )}
                    />

                    <AnimatePresence mode="popLayout">
                        {!collapsed && (
                            <motion.span
                                initial={{ opacity: 0, x: -10 }}
                                animate={{ opacity: 1, x: 0 }}
                                exit={{ opacity: 0, x: -10 }}
                                className="font-medium text-sm tracking-wide whitespace-nowrap"
                            >
                                {label}
                            </motion.span>
                        )}
                    </AnimatePresence>
                </div>

                {/* Hover Glow Effect */}
                <div className="absolute inset-0 bg-gradient-to-r from-primary/0 via-primary/5 to-primary/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-1000 ease-in-out pointer-events-none" />
            </motion.button>
        )
    };

    return (
        <>
            {/* Mobile Overlay */}
            <AnimatePresence>
                {mobileOpen && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 bg-black/80 backdrop-blur-sm z-40 md:hidden"
                        onClick={onMobileClose}
                    />
                )}
            </AnimatePresence>

            {/* Sidebar Container */}
            <motion.aside
                initial={false}
                animate={{ width: collapsed ? 80 : 280 }}
                className={cn(
                    "fixed md:relative z-50 h-full flex flex-col glass-panel-pro border-r border-border-light shadow-2xl overflow-hidden",
                    // Mobile handling
                    mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0",
                    "transition-transform duration-300 md:transition-none"
                )}
            >
                {/* Tech Background Grid */}
                <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-5 pointer-events-none" />
                <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.03)_1px,transparent_1px)] bg-[size:24px_24px] pointer-events-none" />

                {/* Header */}
                <div className="h-20 flex items-center px-6 border-b border-border-light/50 relative z-10">
                    <div className={cn("flex items-center gap-4 w-full transition-all", collapsed ? "justify-center" : "")}>
                        <div className="relative group">
                            <div className="absolute inset-0 bg-primary/40 blur-xl rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
                            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-gray-900 to-black border border-border-light flex items-center justify-center text-primary shadow-lg relative z-10">
                                <Hexagon size={24} className="animate-pulse-glow" strokeWidth={2.5} />
                            </div>
                        </div>

                        {!collapsed && (
                            <motion.div
                                initial={{ opacity: 0, x: -10 }}
                                animate={{ opacity: 1, x: 0 }}
                                className="flex flex-col"
                            >
                                <span className="font-bold text-lg text-text-main tracking-tight font-display">MEDIA<span className="text-primary">AGENT</span></span>
                                <span className="text-[10px] text-text-muted font-mono tracking-widest uppercase flex items-center gap-1">
                                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                                    Online v2.0
                                </span>
                            </motion.div>
                        )}
                    </div>
                </div>

                {/* Nav Items */}
                <div className="flex-1 py-8 px-4 flex flex-col gap-2 overflow-y-auto relative z-10 scrollbar-hide">
                    <div className={cn("px-2 text-[10px] font-bold text-text-muted/40 uppercase tracking-[0.2em] mb-2 font-mono", collapsed && "hidden")}>
                        Core Modules
                    </div>

                    <NavItem icon={LayoutDashboard} label={t('dashboard')} id="dashboard" />
                    <NavItem icon={Activity} label={t('monitoring')} id="monitoring" />

                    <div className="my-6 border-t border-border-light/30 mx-2" />

                    <div className={cn("px-2 text-[10px] font-bold text-text-muted/40 uppercase tracking-[0.2em] mb-2 font-mono", collapsed && "hidden")}>
                        System
                    </div>
                    <NavItem icon={Settings} label={t('settings')} id="settings" />
                </div>

                {/* Footer / Toggle */}
                <div className="p-4 border-t border-border-light/50 relative z-10 bg-panel/50 backdrop-blur-md">
                    <button
                        onClick={() => setCollapsed(!collapsed)}
                        className={cn(
                            "flex items-center justify-center w-full h-10 rounded-lg hover:bg-white/5 text-text-muted hover:text-text-main transition-all duration-300 border border-transparent hover:border-white/10",
                            collapsed && "aspect-square"
                        )}
                    >
                        {collapsed ? <ChevronRight size={18} /> : (
                            <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider">
                                <ChevronLeft size={16} />
                                <span>Collapse View</span>
                            </div>
                        )}
                    </button>

                    {!collapsed && (
                        <div className="mt-4 flex items-center justify-between text-[10px] text-text-muted/30 font-mono">
                            <span className="flex items-center gap-1"><Cpu size={10} /> 12%</span>
                            <span>MEM: 1.2GB</span>
                        </div>
                    )}
                </div>
            </motion.aside>
        </>
    );
}
