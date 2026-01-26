
import { useEffect, useState } from 'react';
import { Save, Loader2, Key, Database, Image as ImageIcon, Monitor } from 'lucide-react';
import { cn } from '../lib/utils';
import { useTranslation } from '../lib/language';
import { useTheme } from 'next-themes';

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

    useEffect(() => {
        fetchSettings();
    }, []);

    const fetchSettings = async () => {
        setLoading(true);
        try {
            const res = await fetch("http://localhost:8000/api/settings");
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
        setMsg(null);
        try {
            const res = await fetch("http://localhost:8000/api/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(config)
            });
            if (res.ok) {
                setMsg({ type: 'success', text: 'Settings saved successfully!' });
                setTimeout(() => setMsg(null), 3000);
            } else {
                setMsg({ type: 'error', text: 'Failed to save settings.' });
            }
        } catch (e) {
            setMsg({ type: 'error', text: 'Network error saving settings.' });
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
        <div className="p-8 glass-panel rounded-xl max-w-5xl mx-auto w-full mt-4 flex flex-col gap-8">
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

            {msg && (
                <div className={cn(
                    "p-3 rounded-lg text-sm font-medium",
                    msg.type === 'success' ? "bg-green-500/10 text-green-400 border border-green-500/20" : "bg-red-500/10 text-red-400 border border-red-500/20"
                )}>
                    {msg.text}
                </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">

                {/* Column 1: Appearance & API */}
                <div className="space-y-8">

                    {/* UI Appearance */}
                    <div className="space-y-6">
                        <SectionLabel icon={<Monitor />} label={t('nav_appearance')} />
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

                {/* Column 2: LLM & Output */}
                <div className="space-y-8">
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
                                    className="w-full glass-panel bg-black/10 px-3 py-2 rounded-lg border-border/30 focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all"
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
                                    className="w-full glass-panel bg-black/10 px-3 py-2 rounded-lg border-border/30 focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all"
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
                className="w-full glass-panel bg-black/10 px-4 py-2.5 rounded-lg border-border/30 focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all placeholder:text-muted/50"
            />
        </div>
    )
}
