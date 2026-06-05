import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { apiUrl } from './api';
import { SystemStatusContext, type SystemStatus, type SystemStatusContextValue } from './systemStatusContext';

export function SystemStatusProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [online, setOnline] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(apiUrl('/api/status'));
      if (!response.ok) throw new Error(`Status request failed (${response.status})`);
      setStatus(await response.json());
      setOnline(true);
    } catch {
      setOnline(false);
      setStatus(null);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = window.setInterval(refresh, 2000);
    return () => window.clearInterval(interval);
  }, [refresh]);

  const value = useMemo<SystemStatusContextValue>(() => ({
    status,
    online,
    running: !!status?.running,
    refresh,
  }), [status, online, refresh]);

  return (
    <SystemStatusContext.Provider value={value}>
      {children}
    </SystemStatusContext.Provider>
  );
}
