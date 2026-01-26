
import { useState, useEffect } from 'react';
import { Sidebar } from './components/Sidebar';
import { FolderPicker } from './components/FolderPicker';
import { TerminalView } from './components/TerminalView';
import { SettingsView } from './components/SettingsView';
import { Play, ShieldAlert, Cpu, Users } from 'lucide-react';
import { cn } from './lib/utils';

function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [selectedPath, setSelectedPath] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [workers, setWorkers] = useState(4);
  const [dryRun, setDryRun] = useState(true);

  // Status Check
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch("http://localhost:8000/api/status");
        if (res.ok) {
          const data = await res.json();
          setIsRunning(data.running);
        }
      } catch (e) { }
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  const handleStart = async () => {
    if (!selectedPath) return;
    try {
      const res = await fetch("http://localhost:8000/api/tasks/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          input_dir: selectedPath,
          dry_run: dryRun,
          inplace: !dryRun,
          workers: workers
        })
      });
      if (res.ok) {
        setIsRunning(true);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const renderContent = () => {
    switch (activeTab) {
      case 'dashboard':
        return (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 h-full pb-6">
            {/* Left: Config & Files */}
            <div className="flex flex-col gap-6 lg:col-span-1">
              <div className="p-6 glass-panel rounded-xl space-y-6">
                <h3 className="font-semibold flex items-center gap-2 text-lg text-primary">
                  <Cpu className="w-5 h-5" />
                  Task Configuration
                </h3>

                {/* Dry Run Toggle */}
                <div
                  className={cn(
                    "flex items-center justify-between p-4 rounded-lg cursor-pointer border transition-all duration-300",
                    "hover:bg-white/5",
                    dryRun ? "border-primary/50 bg-primary/5" : "border-border/50 bg-black/20"
                  )}
                  onClick={() => setDryRun(!dryRun)}
                >
                  <div className="flex flex-col">
                    <span className="text-sm font-semibold">Dry Run Mode</span>
                    <span className="text-xs text-secondary mt-1">Preview changes only</span>
                  </div>
                  <div className={`w-12 h-6 rounded-full relative transition-colors duration-300 ${dryRun ? 'bg-primary shadow-[0_0_10px_var(--accent-primary)]' : 'bg-slate-600'}`}>
                    <div className={`absolute w-4 h-4 bg-white rounded-full top-1 transition-all duration-300 ${dryRun ? 'left-7' : 'left-1'}`} />
                  </div>
                </div>

                {/* Workers Slider */}
                <div className="flex flex-col gap-3">
                  <label className="text-xs text-secondary font-medium uppercase tracking-wider pl-1">Concurrency</label>
                  <div className="flex items-center gap-4 p-4 rounded-lg border border-border/50 bg-black/20">
                    <Users className="w-5 h-5 text-primary" />
                    <div className="flex-1 flex flex-col gap-2">
                      <div className="flex justify-between text-sm">
                        <span className="text-secondary">Workers</span>
                        <span className="font-mono text-primary font-bold">{workers}</span>
                      </div>
                      <input
                        type="range"
                        min="1"
                        max="16"
                        step="1"
                        value={workers}
                        onChange={(e) => setWorkers(parseInt(e.target.value))}
                        className="w-full h-1 bg-white/20 rounded-lg appearance-none cursor-pointer accent-primary"
                      />
                    </div>
                  </div>
                </div>

                {!dryRun && (
                  <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-lg text-sm text-red-300 flex gap-3 items-start animate-in fade-in slide-in-from-top-2">
                    <ShieldAlert className="w-5 h-5 shrink-0 text-red-400" />
                    <div className="font-medium">
                      Warning: Files will be renamed in-place!
                    </div>
                  </div>
                )}

                {/* Start Button */}
                <button
                  disabled={isRunning || !selectedPath}
                  onClick={handleStart}
                  className="w-full py-4 bg-primary hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-xl font-bold flex items-center justify-center gap-2 transition-all shadow-[0_0_20px_rgba(var(--accent-primary),0.3)] hover:shadow-[0_0_30px_rgba(var(--accent-primary),0.5)] active:scale-[0.98]"
                >
                  <Play className="w-5 h-5 fill-current" />
                  Start Processing
                </button>
              </div>

              <FolderPicker className="flex-1 glass-panel rounded-xl overflow-hidden" onSelect={setSelectedPath} />
            </div>

            {/* Right: Terminal */}
            <div className="lg:col-span-2 h-full min-h-[500px]">
              <TerminalView className="h-full glass-panel rounded-xl border border-border/50 shadow-2xl" />
            </div>
          </div>
        );
      case 'monitoring':
        return (
          <div className="h-full flex flex-col gap-4">
            <div className="glass-panel p-4 rounded-xl flex items-center gap-4">
              <div className="flex-1">
                <h3 className="text-lg font-bold">Activity Log</h3>
                <p className="text-xs text-secondary">Real-time processing logs</p>
              </div>
            </div>
            <div className="flex-1 glass-panel rounded-xl border border-border/50 shadow-2xl overflow-hidden">
              <TerminalView className="h-full" />
            </div>
          </div>
        );
      case 'settings':
        return <SettingsView />;
      default:
        return null;
    }
  }

  return (
    <div className="flex h-screen w-full overflow-hidden text-foreground">
      <Sidebar activeTab={activeTab} onTabChange={setActiveTab} />

      <main className="flex-1 flex flex-col p-6 gap-6 overflow-y-auto relative">
        <header className="flex justify-between items-center glass-panel px-6 py-4 rounded-xl z-10 sticky top-0 shrink-0">
          <h2 className="text-2xl font-bold bg-gradient-to-r from-primary to-violet-400 bg-clip-text text-transparent capitalize">
            {activeTab}
          </h2>
          {isRunning && (
            <div className="flex items-center gap-2 px-3 py-1 bg-green-500/20 text-green-400 border border-green-500/30 rounded-full text-xs font-medium animate-pulse">
              <span className="w-2 h-2 rounded-full bg-green-500 shadow-[0_0_10px_#22c55e]"></span>
              Running
            </div>
          )}
        </header>

        <div className="flex-1 min-h-0">
          {renderContent()}
        </div>
      </main>
    </div>
  )
}

export default App
