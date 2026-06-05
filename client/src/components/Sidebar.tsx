import { useState } from 'react';
import { LayoutDashboard, Settings, Activity, ChevronRight, type LucideIcon } from 'lucide-react';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/languageContext';
import { motion, AnimatePresence } from 'framer-motion';

interface SidebarProps {
    activeTab: string;
    onTabChange: (tab: string) => void;
    mobileOpen?: boolean;
    onMobileClose?: () => void;
}

interface NavItemProps {
    icon: LucideIcon;
    label: string;
    id: string;
    activeTab: string;
    collapsed: boolean;
    onSelect: (tab: string) => void;
}

function NavItem({ icon: Icon, label, id, activeTab, collapsed, onSelect }: NavItemProps) {
    const isActive = activeTab === id;

    return (
        <button
            onClick={() => onSelect(id)}
            className="group flex items-center w-full outline-none"
        >
            <div className="h-12 w-full flex items-center px-0">
                <div className="w-[84px] shrink-0 flex items-center justify-center">
                    <div className={cn(
                        "w-10 h-10 rounded-xl flex items-center justify-center transition-[transform,colors] duration-300",
                        isActive
                            ? "scale-110 text-primary dark:text-ios-green"
                            : "text-text-muted group-hover:text-text-main group-hover:scale-105"
                    )}>
                        <Icon
                            size={20}
                            strokeWidth={isActive ? 2.5 : 2}
                        />
                    </div>
                </div>

                <div className={cn(
                    "flex-1 overflow-hidden whitespace-nowrap transition-opacity duration-300 flex items-center",
                    collapsed ? "opacity-0 w-0 pointer-events-none" : "opacity-100"
                )}>
                    <span className={cn(
                        "font-medium text-sm tracking-wide pl-2 transition-colors duration-300",
                        isActive
                            ? "text-primary dark:text-ios-green font-bold"
                            : "text-text-muted group-hover:text-text-main"
                    )}>
                        {label}
                    </span>
                </div>
            </div>
        </button>
    )
}

export function Sidebar({ activeTab, onTabChange, mobileOpen = false, onMobileClose }: SidebarProps) {
    const { t } = useTranslation();
    const [collapsed, setCollapsed] = useState(true);

    const handleSelect = (tab: string) => {
        onTabChange(tab);
        if (window.innerWidth < 768) onMobileClose?.();
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
                        className="fixed inset-0 bg-black/40 backdrop-blur-sm z-40 md:hidden"
                        onClick={onMobileClose}
                    />
                )}
            </AnimatePresence>

            {/* Sidebar Container */}
            <motion.aside
                initial={false}
                animate={{ width: collapsed ? 84 : 260 }}
                transition={{ type: "spring", stiffness: 300, damping: 30 }}
                onMouseLeave={() => setCollapsed(true)}
                className={cn(
                    "fixed md:relative z-50 flex flex-col glass-panel-pro shadow-2xl overflow-hidden",
                    // Floating logic
                    "h-[calc(100vh-2rem)] my-4 ml-4 rounded-3xl border border-glass-border",
                    mobileOpen ? "translate-x-0" : "-translate-x-[120%] md:translate-x-0"
                )}
            >
                {/* Tech Background Grid (Subtle) */}
                <div className="absolute inset-0 bg-noise opacity-[0.02] pointer-events-none" />

                {/* Header - Fixed Height & Centered Content - Adjusted to match Top Bar center alignment */}
                <div className="h-[88px] shrink-0 flex items-center relative z-10 w-full mb-2">
                    <div className="flex items-center w-full px-0">
                        {/* Icon centered in the 84px column */}
                        <div className="w-[84px] shrink-0 flex justify-center items-center">
                            <div className="relative group cursor-pointer">
                                <div className="absolute inset-0 bg-primary/40 blur-xl rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
                                <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-[#007AFF] to-[#5856D6] dark:from-[#34C759] dark:to-[#30B0C7] flex items-center justify-center text-white shadow-lg shadow-primary/20 relative z-10 ring-1 ring-white/20 group-hover:scale-105 transition-transform duration-300">
                                    <div className="absolute inset-0 rounded-2xl bg-gradient-to-tr from-white/20 to-transparent opacity-50" />
                                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" className="relative z-20">
                                        <path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                        <path d="M2 17L12 22L22 17" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                        <path d="M2 12L12 17L22 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                    </svg>
                                </div>
                            </div>
                        </div>

                        {/* Title Text */}
                        <div className={cn(
                            "flex-1 overflow-hidden whitespace-nowrap transition-opacity duration-300",
                            collapsed ? "opacity-0 w-0" : "opacity-100"
                        )}>
                            <span className="font-bold text-lg text-text-main tracking-tight font-display whitespace-nowrap pl-2">
                                Media<span className="text-primary">Agent</span>
                            </span>
                        </div>
                    </div>
                </div>



                {/* Nav Items */}
                <div className="flex-1 py-2 flex flex-col gap-2 overflow-y-auto overflow-x-hidden relative z-10 scrollbar-hide items-center">
                    <NavItem icon={LayoutDashboard} label={t('dashboard')} id="dashboard" activeTab={activeTab} collapsed={collapsed} onSelect={handleSelect} />
                    <NavItem icon={Activity} label={t('monitoring')} id="monitoring" activeTab={activeTab} collapsed={collapsed} onSelect={handleSelect} />

                    <div className="h-4" /> {/* Spacer instead of divider */}

                    <NavItem icon={Settings} label={t('settings')} id="settings" activeTab={activeTab} collapsed={collapsed} onSelect={handleSelect} />
                </div>


                {/* Footer / Toggle */}
                <div className="h-20 shrink-0 flex items-center relative z-10 w-full">
                    <div className="flex items-center w-full px-0">
                        {/* Toggle Button centered in 84px column */}
                        <div className="w-[84px] shrink-0 flex justify-center">
                            <button
                                onClick={() => setCollapsed(!collapsed)}
                                className="flex items-center justify-center w-10 h-10 rounded-full hover:bg-black/5 dark:hover:bg-white/10 text-text-muted hover:text-primary transition-all duration-300"
                            >
                                <motion.div
                                    animate={{ rotate: collapsed ? 0 : 180 }}
                                    transition={{ duration: 0.3 }}
                                >
                                    <ChevronRight size={20} />
                                </motion.div>
                            </button>
                        </div>
                    </div>
                </div>
            </motion.aside>
        </>
    );
}
