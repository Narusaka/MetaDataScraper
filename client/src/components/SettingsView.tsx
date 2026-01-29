
import { useEffect, useState } from 'react';
import { Save, Loader2, Key, Database, Image as ImageIcon, Monitor, Cpu, Bell, CheckCircle2, XCircle } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/language';
import { useTheme } from 'next-themes';
import { apiUrl } from '../lib/api';

// Loose typing for the config 
interface Config {
    tmdb?: { api_key: string };
    omdb?: { api_key: string };
    google?: { api_key: string; search_engine_id: string };
    model?: {
        base_url: string;
        api_key: string;
        model: string;
        temperature?: number;
    };
    output?: {
        image_limit?: {
            posters: number;
            backdrops: number;
        }
    }
    [key: string]: any;
}

export function SettingsView() {
    const { t, language, setLanguage } = useTranslation();
    const { theme, setTheme } = useTheme();
    const [config, setConfig] = useState<Config | null>(null);
    const [loading, setLoading] = useState(false);
    const [saving, setSaving] = useState(false);
    const [msg, setMsg] = useState<{ type: 'success' | 'error', text: string } | null>(null);
    const [workers, setWorkers] = useState(() => parseInt(localStorage.getItem('task_workers') || "4"));

    useEffect(() => {
        fetchSettings();
    }, []);

    const fetchSettings = async () => {
        setLoading(true);
        try {
            const res = await fetch(apiUrl('/api/settings'));
            if (res.ok) {
                const data = await res.json();
                setConfig(data);
            }
        } catch (e) {
            console.error("Failed to load settings", e);
        } finally {
            setLoading(false);
        }
    };

    const handleSave = async () => {
        if (!config) return;
        setSaving(true);
        // Clear previous msg to force re-render if needed or just update
        setMsg(null);

        try {
            const res = await fetch(apiUrl('/api/settings'), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(config)
            });
            if (res.ok) {
                setMsg({ type: 'success', text: 'Settings saved successfully!' });
                setTimeout(() => setMsg(null), 3000);
            } else {
                setMsg({ type: 'error', text: 'Failed to save settings.' });
                setTimeout(() => setMsg(null), 3000);
            }
        } catch (e) {
            setMsg({ type: 'error', text: 'Network error saving settings.' });
            setTimeout(() => setMsg(null), 3000);
        } finally {
            setSaving(false);
        }
    };

    const updateConfig = (section: string, key: string, value: any) => {
        if (!config) return;
        setConfig(prev => {
            if (!prev) return null;
            return {
                ...prev,
                [section]: {
                    ...prev[section],
                    [key]: value
                }
            };
        });
    };

    if (loading && !config) {
        return <div className="flex justify-center p-12"><Loader2 className="animate-spin" /></div>;
    }


    if (!config) return <div>Error loading config.</div>;

    return (
        <div className="p-6 glass-panel-pro rounded-3xl w-full h-full flex flex-col gap-8 relative overflow-hidden">
            {/* Toast Notification Layer */}
            <AnimatePresence>
                {msg && (
                    <motion.div
                        initial={{ opacity: 0, y: -50, x: '-50%' }}
                        animate={{ opacity: 1, y: 20, x: '-50%' }}
                        exit={{ opacity: 0, y: -50, x: '-50%' }}
                        className={cn(
                            "absolute top-0 left-1/2 z-50 flex items-center gap-3 px-6 py-3 rounded-full shadow-2xl backdrop-blur-md border",
                            msg.type === 'success' ? "bg-white/90 dark:bg-zinc-800/90 text-green-600 border-green-500/20" : "bg-white/90 dark:bg-zinc-800/90 text-red-500 border-red-500/20"
                        )}
                    >
                        {msg.type === 'success' ? <CheckCircle2 size={18} /> : <XCircle size={18} />}
                        <span className="text-sm font-bold tracking-wide text-zinc-800 dark:text-zinc-100">{msg.text}</span>
                    </motion.div>
                )}
            </AnimatePresence>

            <div className="flex justify-between items-center">
                <div>
                    <h3 className="text-2xl font-bold flex items-center gap-3">
                        {t('settings')}
                    </h3>
                    <p className="text-sm text-secondary">Manage system preferences and API connections.</p>
                </div>
                <button
                    onClick={handleSave}
                    disabled={saving}
                    className="px-6 py-2 bg-primary hover:bg-primary/90 text-white rounded-lg font-medium flex items-center gap-2 transition-all disabled:opacity-50 shadow-lg shadow-primary/20"
                >
                    {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                    Save Changes
                </button>
            </div>



            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">

                {/* Column 1: Appearance & API */}
                <div className="space-y-8">

                    {/* UI Appearance */}
                    <div className="space-y-6">
                        <div className="flex justify-between items-center">
                            <SectionLabel icon={<Monitor />} label={t('nav_appearance')} />
                            <ProxyTester />
                        </div>
                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <label className="text-xs text-secondary font-medium uppercase">Theme</label>
                                <div className="flex bg-black/10 rounded-lg p-1 border border-border/30">
                                    <button
                                        onClick={() => setTheme('light')}
                                        className={cn("flex-1 py-1.5 text-xs rounded transition-all", theme === 'light' ? "bg-white text-black shadow-sm" : "text-secondary hover:text-foreground")}
                                    >Light</button>
                                    <button
                                        onClick={() => setTheme('dark')}
                                        className={cn("flex-1 py-1.5 text-xs rounded transition-all", theme === 'dark' ? "bg-slate-700 text-white shadow-sm" : "text-secondary hover:text-foreground")}
                                    >Dark</button>
                                </div>
                            </div>
                            <div className="space-y-2">
                                <label className="text-xs text-secondary font-medium uppercase">Language</label>
                                <div className="flex bg-black/10 rounded-lg p-1 border border-border/30">
                                    <button
                                        onClick={() => setLanguage('en')}
                                        className={cn("flex-1 py-1.5 text-xs rounded transition-all", language === 'en' ? "bg-primary text-white shadow-sm" : "text-secondary hover:text-foreground")}
                                    >EN</button>
                                    <button
                                        onClick={() => setLanguage('zh')}
                                        className={cn("flex-1 py-1.5 text-xs rounded transition-all", language === 'zh' ? "bg-primary text-white shadow-sm" : "text-secondary hover:text-foreground")}
                                    >中文</button>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="space-y-6">
                        <SectionLabel icon={<Key />} label="API Keys" />
                        <div className="space-y-4">
                            <InputGroup
                                label="TMDB API Key"
                                value={config.tmdb?.api_key || ""}
                                onChange={(v) => updateConfig('tmdb', 'api_key', v)}
                                type="password"
                            />
                            <InputGroup
                                label="OMDB API Key"
                                value={config.omdb?.api_key || ""}
                                onChange={(v) => updateConfig('omdb', 'api_key', v)}
                                type="password"
                            />
                        </div>
                    </div>

                </div>

                {/* Column 2: LLM & Output & Execution */}
                <div className="space-y-8">

                    {/* Execution Settings (Client Side) */}
                    <div className="space-y-6">
                        <SectionLabel icon={<Cpu />} label="Task Execution" />
                        <div className="space-y-4">
                            <div className="glass-panel-pro bg-black/5 dark:bg-black/20 px-6 py-5 rounded-2xl border border-white/10">
                                <div className="flex justify-between items-center mb-4">
                                    <label className="text-xs text-secondary font-bold uppercase tracking-wider">Thread Allocation</label>
                                    <span className="text-sm font-mono font-bold text-primary bg-primary/10 px-2 py-0.5 rounded">
                                        {workers} CORES
                                    </span>
                                </div>

                                <MacOsSlider
                                    min={1}
                                    max={16}
                                    value={workers}
                                    onChange={(val: number) => {
                                        setWorkers(val);
                                        localStorage.setItem('task_workers', val.toString());
                                    }}
                                    icon={<Cpu size={14} className="text-secondary" />}
                                />

                                <p className="text-[10px] text-muted-foreground mt-4 leading-relaxed opacity-70">
                                    Determines how many concurrent scraping tasks run. Higher values speed up processing but require more CPU/RAM.
                                </p>
                            </div>
                        </div>
                    </div>

                    <div className="space-y-6">
                        <SectionLabel icon={<Database />} label="LLM Configuration" />
                        <div className="space-y-4">
                            <InputGroup
                                label="Model Base URL"
                                value={config.model?.base_url || ""}
                                onChange={(v) => updateConfig('model', 'base_url', v)}
                                placeholder="http://localhost:8045/v1"
                            />
                            <InputGroup
                                label="Model API Key"
                                value={config.model?.api_key || ""}
                                onChange={(v) => updateConfig('model', 'api_key', v)}
                                placeholder="EMPTY"
                                type="password"
                            />
                            <InputGroup
                                label="Model Name"
                                value={config.model?.model || ""}
                                onChange={(v) => updateConfig('model', 'model', v)}
                                placeholder="gemini-3-flash"
                            />
                        </div>
                    </div>

                    <div className="space-y-6">
                        <SectionLabel icon={<ImageIcon />} label="Output Settings" />

                        <div className="flex gap-4">
                            <div className="flex-1">
                                <label className="text-xs text-secondary font-medium mb-1 block">Poster Limit</label>
                                <input
                                    type="number"
                                    className="w-full glass-panel-pro bg-black/10 px-3 py-2 rounded-lg border-border/30 focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all"
                                    value={config.output?.image_limit?.posters || 20}
                                    onChange={(e) => {
                                        const val = parseInt(e.target.value);
                                        setConfig(prev => ({
                                            ...prev!,
                                            output: {
                                                ...prev?.output,
                                                image_limit: {
                                                    ...prev?.output?.image_limit,
                                                    posters: val
                                                }
                                            }
                                        }))
                                    }}
                                />
                            </div>
                            <div className="flex-1">
                                <label className="text-xs text-secondary font-medium mb-1 block">Backdrop Limit</label>
                                <input
                                    type="number"
                                    className="w-full glass-panel-pro bg-black/10 px-3 py-2 rounded-lg border-border/30 focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all"
                                    value={config.output?.image_limit?.backdrops || 5}
                                    onChange={(e) => {
                                        const val = parseInt(e.target.value);
                                        setConfig(prev => ({
                                            ...prev!,
                                            output: {
                                                ...prev?.output,
                                                image_limit: {
                                                    ...prev?.output?.image_limit,
                                                    backdrops: val
                                                }
                                            }
                                        }))
                                    }}
                                />
                            </div>
                        </div>
                    </div>
                </div>

            </div>
        </div>
    );
}

function SectionLabel({ icon, label }: { icon: any, label: string }) {
    return (
        <div className="flex items-center gap-2 text-primary border-b border-border/30 pb-2">
            <span className="w-5 h-5">{icon}</span>
            <h4 className="font-semibold">{label}</h4>
        </div>
    );
}

function InputGroup({ label, value, onChange, placeholder, type = "text" }: {
    label: string,
    value: string,
    onChange: (val: string) => void,
    placeholder?: string,
    type?: string
}) {
    return (
        <div className="space-y-1">
            <label className="text-xs text-secondary font-medium ml-1">{label}</label>
            <input
                type={type}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                placeholder={placeholder}
                className="w-full glass-panel-pro bg-black/10 px-4 py-2.5 rounded-lg border-border/30 focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all placeholder:text-muted/50"
            />
        </div>
    )
}

function ProxyTester() {
    const [status, setStatus] = useState<any>(null);
    const [loading, setLoading] = useState(false);

    const check = async () => {
        setLoading(true);
        setStatus(null);
        try {
            const res = await fetch(apiUrl('/api/test_connectivity'));
            if (res.ok) {
                const data = await res.json();
                setStatus(data);
            } else {
                setStatus({ error: "API failed" });
            }
        } catch (e) {
            setStatus({ error: "Network error" });
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="flex flex-col items-end gap-2">
            <button
                onClick={check}
                disabled={loading}
                className="text-[10px] font-bold uppercase tracking-widest px-3 py-1.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg flex items-center gap-2 transition-all"
            >
                {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Monitor className="w-3 h-3" />}
                Test Connectivity
            </button>
            {status && (
                <div className="flex gap-2">
                    {['tmdb', 'google'].map(service => (
                        <div key={service} className={cn(
                            "px-2 py-0.5 rounded text-[8px] font-bold uppercase tracking-tighter border",
                            status[service]?.status === 'ok'
                                ? "bg-green-500/10 border-green-500/30 text-green-400"
                                : "bg-red-500/10 border-red-500/30 text-red-400"
                        )}>
                            {service}: {status[service]?.status || 'error'}
                        </div>
                    ))}
                    {status.error && <div className="text-[8px] text-red-400">{status.error}</div>}
                </div>
            )}
        </div>
    );
}


function MacOsSlider({ min, max, value, onChange, icon }: any) {
    const percentage = ((value - min) / (max - min)) * 100;

    return (
        <div className="relative h-6 w-full flex items-center select-none group">
            {/* Icon Label (Optional) */}
            {icon && <div className="absolute -left-6">{icon}</div>}

            {/* Slider Input (Invisible but interactive, full hit area) */}
            <input
                type="range"
                min={min}
                max={max}
                value={value}
                onChange={(e) => onChange(parseInt(e.target.value))}
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-20"
            />

            {/* Track Background (Gray Line) */}
            <div className="absolute w-full h-1 bg-gray-300 dark:bg-gray-600 rounded-full overflow-hidden pointer-events-none">
                {/* Active Track (Blue Line) - Only fills up to the percentage */}
                <div
                    className="h-full bg-blue-500"
                    style={{ width: `${percentage}%` }}
                />
            </div>

            {/* Knob (Visual only, follows percentage) */}
            <div
                className="absolute w-5 h-5 bg-white rounded-full shadow-[0_1px_3px_rgba(0,0,0,0.3)] border border-gray-200 pointer-events-none z-10 transition-transform active:scale-110"
                style={{
                    left: `calc(${percentage}% - 10px)`
                }}
            />
        </div>
    )
}

