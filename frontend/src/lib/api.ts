import { QueryClient } from '@tanstack/react-query';
import * as Sentry from '@sentry/react';

const API_BASE = import.meta.env.VITE_API_URL || '/api';

export class ApiError extends Error {
  status: number;
  retryAfter?: number;

  constructor(message: string, status: number, retryAfter?: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 30,
      retry: (failureCount, error) => {
        // Don't retry on 401 unauthorized or 429 rate limited
        if (error instanceof ApiError) {
          if (error.status === 401 || error.status === 429) {
            return false;
          }
        }
        return failureCount < 2;
      },
      refetchOnWindowFocus: false,
    },
  },
});

function getAccessToken(): string {
  return localStorage.getItem('nukelab-token') || '';
}

function getRefreshToken(): string {
  return localStorage.getItem('nukelab-refresh') || '';
}

export function setTokens(access: string, refresh: string) {
  localStorage.setItem('nukelab-token', access);
  localStorage.setItem('nukelab-refresh', refresh);
  document.cookie = `nukelab_token=${access}; path=/; Domain=localhost; SameSite=Lax`;
}

function clearTokens() {
  localStorage.removeItem('nukelab-token');
  localStorage.removeItem('nukelab-refresh');
  document.cookie = 'nukelab_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
}

function redirectToLogin() {
  if (window.location.pathname !== '/login') {
    window.location.href = '/login';
  }
}

let isRefreshing = false;
let refreshPromise: Promise<boolean> | null = null;

async function doRefresh(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;

  try {
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!response.ok) {
      clearTokens();
      return false;
    }

    const data = await response.json();
    setTokens(data.access_token, data.refresh_token);
    return true;
  } catch {
    clearTokens();
    return false;
  }
}

export async function refreshAccessToken(): Promise<boolean> {
  if (isRefreshing && refreshPromise) {
    return refreshPromise;
  }

  isRefreshing = true;
  refreshPromise = doRefresh().finally(() => {
    isRefreshing = false;
    refreshPromise = null;
  });

  return refreshPromise;
}

async function parseJson<T>(response: Response): Promise<T> {
  const text = await response.text();
  return text ? JSON.parse(text) : undefined as T;
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const makeRequest = (token: string): Promise<Response> =>
    fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });

  // First attempt
  let response = await makeRequest(getAccessToken());

  // If 401, try to refresh and retry once
  if (response.status === 401) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      response = await makeRequest(getAccessToken());
    } else {
      redirectToLogin();
      throw new Error('Session expired. Please log in again.');
    }
  }

  if (!response.ok) {
    // Try to get detailed error message from response body
    let detail = response.statusText;
    let retryAfter: number | undefined;
    try {
      const body = await response.json();
      detail = body.detail || body.message || response.statusText;
      if (response.status === 429 && body.retry_after) {
        retryAfter = body.retry_after;
        detail = `${detail} Retry in ${body.retry_after}s.`;
      }
    } catch {
      // ignore JSON parse errors
    }
    const error = new ApiError(detail, response.status, retryAfter);
    // Capture server errors (5xx) in Sentry
    if (response.status >= 500) {
      Sentry.captureException(error, {
        tags: { api_endpoint: path, api_status: String(response.status) },
        extra: { response_detail: detail },
      });
    }
    throw error;
  }

  return parseJson<T>(response);
}

export const api = {
  async get<T>(path: string): Promise<T> {
    return apiFetch<T>(path);
  },

  async post<T>(path: string, data: unknown): Promise<T> {
    return apiFetch<T>(path, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async put<T>(path: string, data: unknown): Promise<T> {
    return apiFetch<T>(path, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  async patch<T>(path: string, data: unknown): Promise<T> {
    return apiFetch<T>(path, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  async delete<T>(path: string, queryParams?: Record<string, string>): Promise<T> {
    const queryString = queryParams ? '?' + new URLSearchParams(queryParams).toString() : '';
    return apiFetch<T>(path + queryString, {
      method: 'DELETE',
    });
  },

  async download(path: string, filename?: string): Promise<void> {
    const response = await fetch(`${API_BASE}${path}`, {
      headers: {
        'Authorization': `Bearer ${getAccessToken()}`,
      },
    });

    if (response.status === 401) {
      const refreshed = await refreshAccessToken();
      if (refreshed) {
        return this.download(path, filename);
      }
      redirectToLogin();
      throw new Error('Session expired. Please log in again.');
    }

    if (!response.ok) {
      let detail = response.statusText;
      let retryAfter: number | undefined;
      try {
        const body = await response.json();
        detail = body.detail || body.message || response.statusText;
        if (response.status === 429 && body.retry_after) {
          retryAfter = body.retry_after;
          detail = `${detail} Retry in ${body.retry_after}s.`;
        }
      } catch {
        // ignore
      }
      const error = new ApiError(detail, response.status, retryAfter);
      // Capture server errors (5xx) in Sentry
      if (response.status >= 500) {
        Sentry.captureException(error, {
          tags: { api_endpoint: path, api_status: String(response.status) },
          extra: { response_detail: detail },
        });
      }
      throw error;
    }

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
