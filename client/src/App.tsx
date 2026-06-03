import { useState, useEffect } from 'react';
import { Sidebar } from './components/Sidebar';
import { TerminalView } from './components/TerminalView';
import { SettingsView } from './components/SettingsView';
import { Dashboard } from './components/Dashboard';
import { Header } from './components/Header';
import { Menu, Terminal } from 'lucide-react';
import { apiUrl } from './lib/api';
import { cn } from './lib/utils';
import { Toaster } from 'sonner';

function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [isRunning, setIsRunning] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Status Check (Global)
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(apiUrl('/api/status'));
        if (res.ok) {
          const data = await res.json();
          setIsRunning(data.running);
        }
      } catch (e) { }
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  const handleStartTask = async (taskConfig: any) => {
    try {
      const res = await fetch(apiUrl('/api/tasks/start'), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(taskConfig)
      });
      if (res.ok) {
        setIsRunning(true);
      } else {
        const err = await res.json();
        throw new Error(err.detail || 'Unknown error');
      }
    } catch (e) {
      throw e instanceof Error ? e : new Error(String(e));
    }
  };

  const handleStopTask = async () => {
    try {
      await fetch(apiUrl('/api/tasks/stop'), { method: "POST" });
      // We don't verify response strictly, assuming best effort stop
    } catch (e) {
      console.error("Failed to stop task:", e);
    }
  };

  // Toggles for state-persistent tabs using direct visibility control
  const DashboardLayer = (
    <div
      className={cn("absolute inset-x-4 md:inset-x-6 top-0 bottom-4 transition-all duration-300", activeTab === 'dashboard' ? 'opacity-100 translate-y-0 z-10 visible' : 'opacity-0 translate-y-4 z-0 invisible pointer-events-none')}
      style={{ display: activeTab === 'dashboard' ? 'block' : 'none' }}
    >
      <Dashboard isRunning={isRunning} onStart={handleStartTask} onStop={handleStopTask} />
    </div>
  );

  const MonitoringLayer = (
    <div
      className={cn("absolute inset-x-4 md:inset-x-6 top-0 bottom-4 transition-all duration-300", activeTab === 'monitoring' ? 'opacity-100 translate-y-0 z-10 visible' : 'opacity-0 translate-y-4 z-0 invisible pointer-events-none')}
      style={{ display: activeTab === 'monitoring' ? 'block' : 'none' }}
    >
      <div className="h-full flex flex-col gap-4">
        <div className="flex-1 glass-panel-pro rounded-2xl shadow-xl overflow-hidden relative border border-border-light flex flex-col">
          <div className="h-10 border-b border-border-light bg-black/40 flex items-center px-4 gap-2">
            <Terminal size={14} className="text-secondary" />
            <span className="text-xs font-mono text-text-muted uppercase tracking-widest">System Output Logs</span>
          </div>
          <TerminalView className="flex-1" />
        </div>
      </div>
    </div>
  );

  const SettingsLayer = (
    <div
      className={cn("absolute inset-x-4 md:inset-x-6 top-0 bottom-4 transition-all duration-300", activeTab === 'settings' ? 'opacity-100 translate-y-0 z-10 visible' : 'opacity-0 translate-y-4 z-0 invisible pointer-events-none')}
      style={{ display: activeTab === 'settings' ? 'block' : 'none' }}
    >
      <SettingsView />
    </div>
  );

  return (
    <div className="flex h-screen w-full bg-background text-text-main overflow-hidden font-sans selection:bg-primary/30">
      <Sidebar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        mobileOpen={mobileMenuOpen}
        onMobileClose={() => setMobileMenuOpen(false)}
      />

      <main className="flex-1 flex flex-col relative w-full h-full overflow-hidden">
        {/* Mobile Header */}
        <div className="md:hidden h-16 shrink-0 border-b border-border-light flex items-center px-4 bg-panel/80 backdrop-blur-md cursor-pointer z-30" onClick={() => setMobileMenuOpen(true)}>
          <Menu className="mr-3 text-text-muted transition-colors hover:text-white" />
          <span className="font-bold text-lg tracking-tight">Media<span className="text-primary">Agent</span></span>
        </div>

        {/* Desktop Header area if needed, otherwise clean look */}
        <div className="hidden md:block shrink-0 px-6 py-4">
          {/* We can put breadcrumbs or global status here if needed, keeping it clean for now */}
          <Header title={activeTab} isRunning={isRunning} />
        </div>

        {/* Content Area - Mounted but hidden based on activeTab to preserve state */}
        <div className="flex-1 px-4 pb-4 md:px-6 md:pb-4 pt-0 relative z-10 overflow-hidden">
          {DashboardLayer}
          {MonitoringLayer}
          {SettingsLayer}
        </div>
      </main>
      <Toaster
        position="top-center"
        richColors
        theme="system"
        closeButton
        toastOptions={{
          classNames: {
            closeButton: 'top-2 right-2 left-auto transform-none',
          }
        }}
      />
    </div>
  )
}

export default App
