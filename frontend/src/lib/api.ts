import { QueryClient } from '@tanstack/react-query';

const API_BASE = import.meta.env.VITE_API_URL || '/api';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 30,
      retry: (failureCount, error) => {
        // Don't retry on 401 unauthorized
        if (error instanceof Error && error.message.includes('401')) {
          return false;
        }
        return failureCount < 2;
      },
      refetchOnWindowFocus: false,
    },
  },
});

function getToken(): string {
  return localStorage.getItem('nukelab-token') || '';
}

async function parseJson<T>(response: Response): Promise<T> {
  const text = await response.text();
  return text ? JSON.parse(text) : undefined as T;
}

async function handleAuthError(response: Response): Promise<never> {
  if (response.status === 401) {
    localStorage.removeItem('nukelab-token');
    // Only redirect if not already on login page
    if (window.location.pathname !== '/login') {
      window.location.href = '/login';
    }
    throw new Error('Session expired. Please log in again.');
  }
  // Try to get detailed error message from response body
  let detail = response.statusText;
  try {
    const body = await response.json();
    detail = body.detail || body.message || response.statusText;
  } catch {
    // ignore JSON parse errors
  }
  throw new Error(`${detail}`);
}

export const api = {
  async get<T>(path: string): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, {
      headers: {
        'Authorization': `Bearer ${getToken()}`,
        'Content-Type': 'application/json',
      },
    });
    if (!response.ok) await handleAuthError(response);
    return parseJson<T>(response);
  },

  async post<T>(path: string, data: unknown): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${getToken()}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
    });
    if (!response.ok) await handleAuthError(response);
    return parseJson<T>(response);
  },

  async put<T>(path: string, data: unknown): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${getToken()}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
    });
    if (!response.ok) await handleAuthError(response);
    return parseJson<T>(response);
  },

  async delete<T>(path: string): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, {
      method: 'DELETE',
      headers: {
        'Authorization': `Bearer ${getToken()}`,
        'Content-Type': 'application/json',
      },
    });
    if (!response.ok) await handleAuthError(response);
    return parseJson<T>(response);
  },

  async download(path: string, filename?: string): Promise<void> {
    const response = await fetch(`${API_BASE}${path}`, {
      headers: {
        'Authorization': `Bearer ${getToken()}`,
      },
    });
    if (!response.ok) await handleAuthError(response);
    
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename || 'download';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  },
};
