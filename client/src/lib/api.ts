const defaultApiBase = () => {
  const host = typeof window !== 'undefined' && window.location.hostname
    ? window.location.hostname
    : '127.0.0.1';
  return `http://${host}:8000`;
};

const API_BASE =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') || defaultApiBase();

const WS_BASE =
  import.meta.env.VITE_WS_BASE_URL?.replace(/\/$/, '') ||
  API_BASE.replace(/^http/, 'ws');

async function parseJsonResponse<T>(response: Response, fallbackMessage: string): Promise<T> {
  const data = await response.json().catch(() => undefined);
  if (!response.ok) {
    const detail = data && typeof data === 'object' && 'detail' in data ? String(data.detail) : fallbackMessage;
    throw new Error(detail || fallbackMessage);
  }
  return data as T;
}

export async function apiJson<T>(path: string, init?: RequestInit, fallbackMessage = 'Request failed'): Promise<T> {
  const response = await fetch(apiUrl(path), init);
  return parseJsonResponse<T>(response, fallbackMessage);
}

export function apiUrl(path: string): string {
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
}

export function wsUrl(path: string): string {
  return `${WS_BASE}${path.startsWith('/') ? path : `/${path}`}`;
}
