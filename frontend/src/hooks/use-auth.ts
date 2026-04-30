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
  localStorage.removeItem('nukelab-token');
  // Clear server auth cookie
  document.cookie = 'nukelab_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
  // Clear auth store user
  useAuthStore.getState().setUser(null);
  window.location.href = '/login';
}
