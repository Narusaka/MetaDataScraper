import { apiJson } from './api';
import type { AppConfig, ConnectivityStatus, RejectedMatchesResponse, SavedMatchesResponse, SettingsHistoryResponse, SettingsSaveResponse } from './types';

export async function fetchSettings() {
  return apiJson<AppConfig>('/api/settings', undefined, 'Failed to load settings');
}

export async function saveSettings(config: AppConfig) {
  return apiJson<SettingsSaveResponse>(
    '/api/settings',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    },
    'Failed to save settings.',
  );
}

export async function testConnectivity() {
  return apiJson<ConnectivityStatus>('/api/connectivity', undefined, 'Connectivity test failed');
}

export async function fetchSettingsHistory(limit = 10) {
  return apiJson<SettingsHistoryResponse>(
    `/api/settings/history?limit=${encodeURIComponent(limit)}`,
    undefined,
    'Failed to load settings history',
  );
}

export async function fetchSavedMatches() {
  return apiJson<SavedMatchesResponse>('/api/matches/memory', undefined, 'Saved matches unavailable');
}

export async function deleteSavedMatch(matchId: number) {
  return apiJson<{ status: 'deleted'; id: number }>(
    `/api/matches/memory/${matchId}`,
    { method: 'DELETE' },
    'Unable to delete saved match',
  );
}

export async function fetchRejectedMatches() {
  return apiJson<RejectedMatchesResponse>(
    '/api/matches/rejections',
    undefined,
    'Rejected matches unavailable',
  );
}

export async function deleteRejectedMatch(rejectionId: number) {
  return apiJson<{ status: 'deleted'; id: number }>(
    `/api/matches/rejections/${rejectionId}`,
    { method: 'DELETE' },
    'Unable to allow rejected match again',
  );
}
