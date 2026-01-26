
import { useState, useEffect } from 'react';
import { Sidebar } from './components/Sidebar';
import { TerminalView } from './components/TerminalView';
import { SettingsView } from './components/SettingsView';
import { Dashboard } from './components/Dashboard';
import { Header } from './components/Header';
import { cn } from './lib/utils';


function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [isRunning, setIsRunning] = useState(false);

  // Status Check (Global)
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

  const handleStartTask = async (taskConfig: any) => {
    try {
      const res = await fetch("http://localhost:8000/api/tasks/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(taskConfig)
      });
      if (res.ok) {
        setIsRunning(true);
      } else {
        console.error("Failed to start task");
      }
    } catch (e) {
      console.error(e);
    }
  };

  // Render content
  // We use hidden classes to keep components alive (preserving state like Terminal logs)
  const renderContent = () => {
    return (
      <>
        <div className={cn("h-full", activeTab === 'dashboard' ? 'block' : 'hidden')}>
          <Dashboard isRunning={isRunning} onStart={handleStartTask} />
        </div>

        <div className={cn("h-full flex flex-col gap-4", activeTab === 'monitoring' ? 'block' : 'hidden')}>
          <div className="flex-1 glass-panel rounded-xl border border-border/50 shadow-2xl overflow-hidden">
            <TerminalView className="h-full" />
          </div>
        </div>

        <div className={cn("h-full", activeTab === 'settings' ? 'block' : 'hidden')}>
          <SettingsView />
        </div>
      </>
    )
  }

  return (
    <div className="flex h-screen w-full overflow-hidden text-foreground bg-background">
      <Sidebar activeTab={activeTab} onTabChange={setActiveTab} />

      <main className="flex-1 flex flex-col p-6 overflow-y-auto relative">
        <Header title={activeTab} isRunning={isRunning} />

        <div className="flex-1 min-h-0">
          {renderContent()}
        </div>
      </main>
    </div>
  )
}

export default App
