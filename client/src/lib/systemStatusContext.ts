import { createContext, useContext } from 'react';

export interface SystemStatus {
  running: boolean;
  workers: number;
  stats: {
    total_tasks: number;
    total_media: number;
    total_success: number;
    total_failed: number;
    total_duration: number;
  };
}

export interface SystemStatusContextValue {
  status: SystemStatus | null;
  online: boolean;
  running: boolean;
  refresh: () => Promise<void>;
}

export const SystemStatusContext = createContext<SystemStatusContextValue | null>(null);

export function useSystemStatus() {
  const context = useContext(SystemStatusContext);
  if (!context) {
    throw new Error('useSystemStatus must be used within SystemStatusProvider');
  }
  return context;
}
