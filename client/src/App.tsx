
import { useState, useEffect } from 'react';
import { Sidebar } from './components/Sidebar';
import { TerminalView } from './components/TerminalView';
import { SettingsView } from './components/SettingsView';
import { Dashboard } from './components/Dashboard';
import { Header } from './components/Header';
import { cn } from './lib/utils';
import { Menu } from 'lucide-react';


function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [isRunning, setIsRunning] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

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
        const err = await res.json();
        alert(`Failed to start task: ${err.detail || 'Unknown error'}`);
      }
    } catch (e) {
      alert(`Network error starting task: ${e}`);
    }
  };

  // Render content
  const renderContent = () => {
    return (
      <>
        <div className={cn("h-full", activeTab === 'dashboard' ? 'block' : 'hidden')}>
          <Dashboard isRunning={isRunning} onStart={handleStartTask} />
        </div>

        <div className={cn("h-full flex flex-col gap-4", activeTab === 'monitoring' ? 'block' : 'hidden')}>
          <div className="flex-1 panel rounded-2xl shadow-xl overflow-hidden relative">
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
    <div className="flex h-screen w-full bg-background text-text-main overflow-hidden">
      {/* Sidebar - Handles its own mobile/desktop width logic */}
      <Sidebar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        mobileOpen={mobileMenuOpen}
        onMobileClose={() => setMobileMenuOpen(false)}
      />

      <main className="flex-1 flex flex-col relative w-full h-full overflow-hidden transition-all duration-300">
        {/* Mobile Header */}
        <div className="md:hidden h-14 shrink-0 border-b border-border-light flex items-center px-4 bg-panel cursor-pointer" onClick={() => setMobileMenuOpen(true)}>
          <Menu className="mr-3 text-text-muted" />
          <span className="font-bold text-lg">MediaAgent</span>
        </div>

        {/* Desktop Header (Hidden on mobile if needed, or adapted) */}
        <div className="shrink-0 hidden md:block">
          <Header title={activeTab} isRunning={isRunning} />
        </div>

        {/* Content Area */}
        <div className="flex-1 p-4 md:p-6 overflow-y-auto overflow-x-hidden">
          {renderContent()}
        </div>
      </main>
    </div>
  )
}

export default App
