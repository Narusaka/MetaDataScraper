import { lazy, Suspense, useState } from 'react';
import { Sidebar } from './components/Sidebar';
import { OperationsDashboard } from './components/OperationsDashboard';
import { Header } from './components/Header';
import { Menu, Terminal } from 'lucide-react';
import { planTask, stopTasks } from './lib/taskApi';
import { SystemStatusProvider } from './lib/systemStatus';
import { useSystemStatus } from './lib/systemStatusContext';
import type { TaskStartPayload } from './lib/types';
import { Toaster } from 'sonner';

const HistoryView = lazy(() => import('./components/HistoryView').then(module => ({ default: module.HistoryView })));
const PlanningView = lazy(() => import('./components/Dashboard').then(module => ({ default: module.Dashboard })));
const LibraryScanView = lazy(() => import('./components/LibraryScanView').then(module => ({ default: module.LibraryScanView })));
const MatchReviewView = lazy(() => import('./components/MatchReviewView').then(module => ({ default: module.MatchReviewView })));
const PlanReviewView = lazy(() => import('./components/PlanReviewView').then(module => ({ default: module.PlanReviewView })));
const ExecutionView = lazy(() => import('./components/ExecutionView').then(module => ({ default: module.ExecutionView })));
const SettingsView = lazy(() => import('./components/SettingsView').then(module => ({ default: module.SettingsView })));
const TerminalView = lazy(() => import('./components/TerminalView').then(module => ({ default: module.TerminalView })));

function PageFallback() {
  return (
    <div className="h-full flex items-center justify-center rounded-3xl border border-glass-border glass-panel-pro text-xs font-semibold text-text-muted">
      Loading workspace...
    </div>
  );
}

function AppShell() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const { running: isRunning, refresh: refreshStatus } = useSystemStatus();

  const handlePlanTask = async (taskConfig: TaskStartPayload) => {
    try {
      await planTask(taskConfig);
      await refreshStatus();
    } catch (e) {
      throw e instanceof Error ? e : new Error(String(e));
    }
  };

  const handleStopTask = async () => {
    try {
      await stopTasks();
      await refreshStatus();
    } catch (e) {
      console.error("Failed to stop task:", e);
    }
  };

  const renderWorkspace = () => {
    switch (activeTab) {
      case 'dashboard':
        return <OperationsDashboard active onNavigate={setActiveTab} />;
      case 'planning':
        return <PlanningView isRunning={isRunning} onPlan={handlePlanTask} onStop={handleStopTask} />;
      case 'library_scan':
        return <LibraryScanView active />;
      case 'match_review':
        return <MatchReviewView active />;
      case 'plan_review':
        return <PlanReviewView active />;
      case 'execution':
        return <ExecutionView active />;
      case 'history':
        return <HistoryView active />;
      case 'settings':
        return <SettingsView />;
      case 'monitoring':
        return (
          <div className="flex h-full flex-col">
            <div className="relative flex flex-1 flex-col overflow-hidden rounded-2xl border border-border-light glass-panel-pro shadow-xl">
              <div className="flex h-10 items-center gap-2 border-b border-border-light bg-black/40 px-4">
                <Terminal size={14} className="text-secondary" />
                <span className="font-mono text-xs uppercase tracking-widest text-text-muted">System Output Logs</span>
              </div>
              <TerminalView className="flex-1" active />
            </div>
          </div>
        );
      default:
        return <OperationsDashboard active onNavigate={setActiveTab} />;
    }
  };

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
          <Header title={activeTab} />
        </div>

        {/* Workspaces mount on demand so inactive task boards do not poll or inflate the DOM. */}
        <div className="relative z-10 flex-1 overflow-hidden px-4 pb-4 pt-0 md:px-6 md:pb-4">
          <Suspense fallback={<PageFallback />}>
            {renderWorkspace()}
          </Suspense>
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

function App() {
  return (
    <SystemStatusProvider>
      <AppShell />
    </SystemStatusProvider>
  );
}

export default App
