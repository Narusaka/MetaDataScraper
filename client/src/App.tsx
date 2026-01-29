import { useState, useEffect } from 'react';
import { Sidebar } from './components/Sidebar';
import { TerminalView } from './components/TerminalView';
import { SettingsView } from './components/SettingsView';
import { Dashboard } from './components/Dashboard';
import { Header } from './components/Header';
import { Menu, Terminal } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { apiUrl } from './lib/api';

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
        alert(`Failed to start task: ${err.detail || 'Unknown error'}`);
      }
    } catch (e) {
      alert(`Network error starting task: ${e}`);
    }
  };

  // Render content with entry animations
  const renderContent = () => {
    // Determine which component to render
    let ContentComponent;
    switch (activeTab) {
      case 'dashboard':
        ContentComponent = <Dashboard isRunning={isRunning} onStart={handleStartTask} />;
        break;
      case 'monitoring':
        ContentComponent = (
          <div className="h-full flex flex-col gap-4">
            <div className="flex-1 glass-panel-pro rounded-2xl shadow-xl overflow-hidden relative border border-border-light flex flex-col">
              <div className="h-10 border-b border-border-light bg-black/40 flex items-center px-4 gap-2">
                <Terminal size={14} className="text-secondary" />
                <span className="text-xs font-mono text-text-muted">SYSTEM_OUTPUT_STREAM</span>
              </div>
              <TerminalView className="flex-1" />
            </div>
          </div>
        );
        break;
      case 'settings':
        ContentComponent = <SettingsView />;
        break;
      default:
        ContentComponent = <div className="text-center text-text-muted pt-20">Unknown Module</div>;
    }

    return (
      <AnimatePresence mode="wait">
        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 10, filter: 'blur(10px)' }}
          animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
          exit={{ opacity: 0, y: -10, filter: 'blur(10px)' }}
          transition={{ duration: 0.3, ease: "easeOut" }}
          className="h-full"
        >
          {ContentComponent}
        </motion.div>
      </AnimatePresence>
    )
  }

  return (
    <div className="flex h-screen w-full bg-background text-text-main overflow-hidden font-sans selection:bg-primary/30">
      <Sidebar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        mobileOpen={mobileMenuOpen}
        onMobileClose={() => setMobileMenuOpen(false)}
      />

      <main className="flex-1 flex flex-col relative w-full h-full overflow-hidden">
        {/* Background Ambient Glow */}
        <div className="fixed top-[-20%] right-[-10%] w-[600px] h-[600px] bg-primary/5 rounded-full blur-[100px] pointer-events-none" />
        <div className="fixed bottom-[-20%] left-[-10%] w-[500px] h-[500px] bg-emerald-500/5 rounded-full blur-[100px] pointer-events-none" />

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

        {/* Content Area */}
        <div className="flex-1 p-4 md:p-6 pt-0 overflow-y-auto overflow-x-hidden relative z-10 scrollbar-thin">
          {renderContent()}
        </div>
      </main>
    </div>
  )
}

export default App
