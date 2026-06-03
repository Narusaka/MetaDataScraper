const API_BASE =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') || 'http://localhost:8000';

const WS_BASE =
  import.meta.env.VITE_WS_BASE_URL?.replace(/\/$/, '') ||
  API_BASE.replace(/^http/, 'ws');

export function apiUrl(path: string): string {
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
}

export function wsUrl(path: string): string {
  return `${WS_BASE}${path.startsWith('/') ? path : `/${path}`}`;
}
