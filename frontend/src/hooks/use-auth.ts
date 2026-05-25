import { useEffect } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { useAuthStore } from '../stores/auth-store';

export function useAuthGuard(requireAuth = true) {
  const navigate = useNavigate();

  useEffect(() => {
    const token = localStorage.getItem('nukelab-token');
    
    if (requireAuth && !token) {
      // Not logged in, redirect to login
      navigate({ to: '/login' });
    } else if (!requireAuth && token) {
      // Already logged in, redirect to dashboard
      navigate({ to: '/' });
    }
  }, [requireAuth, navigate]);
}

export function isAuthenticated(): boolean {
  return !!localStorage.getItem('nukelab-token');
}

export function logout(): void {
  const refreshToken = localStorage.getItem('nukelab-refresh');
  if (refreshToken) {
    // Fire-and-forget: don't block the UI waiting for server cleanup
    fetch(`${import.meta.env.VITE_API_URL || '/api'}/auth/logout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    }).catch(() => {
      // Ignore errors — local state is already cleared
    });
  }
  // Clear all local state immediately so the UI responds instantly
  localStorage.removeItem('nukelab-token');
  localStorage.removeItem('nukelab-refresh');
  // Clear server auth cookie
  document.cookie = 'nukelab_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
  // Clear auth store user
  useAuthStore.getState().setUser(null);
  // Hard navigation to login — full page reload ensures clean state
  window.location.href = '/login';
}
