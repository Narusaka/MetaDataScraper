
import { LayoutDashboard, Settings, Activity } from 'lucide-react';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/language';

interface SidebarProps {
    activeTab: string;
    onTabChange: (tab: string) => void;
}

export function Sidebar({ activeTab, onTabChange }: SidebarProps) {
    const { t } = useTranslation();

    return (
        <div className="w-16 md:w-64 glass-panel border-y-0 border-l-0 border-r border-border/30 flex flex-col items-center md:items-stretch py-6 gap-2 z-20 h-screen sticky top-0">
            <div className="px-6 mb-8 hidden md:block">
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
            />
            <NavItem
                icon={<Activity />}
                label={t('monitoring')}
                active={activeTab === 'monitoring'}
                onClick={() => onTabChange('monitoring')}
            />

            <div className="flex-1" />

            <NavItem
                icon={<Settings />}
                label={t('settings')}
                active={activeTab === 'settings'}
                onClick={() => onTabChange('settings')}
            />
        </div>
    );
}

interface NavItemProps {
    icon: React.ReactNode;
    label: string;
    active?: boolean;
    onClick?: () => void;
}

function NavItem({ icon, label, active = false, onClick }: NavItemProps) {
    return (
        <div
            onClick={onClick}
            className={cn(
                "flex items-center gap-3 px-6 py-3 mx-2 rounded-lg cursor-pointer transition-all duration-300",
                active
                    ? "bg-primary/20 text-primary border border-primary/20"
                    : "text-secondary hover:bg-white/10 dark:hover:bg-white/5 hover:text-primary"
            )}>
            {icon}
            <span className="hidden md:block font-medium">{label}</span>
        </div>
    );
}
