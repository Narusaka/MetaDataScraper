import type { ConnectivityServiceStatus } from './types';

export type ConnectivityTone = 'success' | 'warning' | 'danger';

export function getConnectivityTone(status?: ConnectivityServiceStatus): ConnectivityTone {
  if (status?.status === 'ok') return 'success';
  if (status?.status === 'skipped') return 'warning';
  return 'danger';
}

export function isConnectivityUsable(status?: ConnectivityServiceStatus): boolean {
  return status?.status === 'ok' || status?.status === 'skipped';
}
