import { useEffect } from 'react';
import { useNavigate } from '@tanstack/react-router';

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
  window.location.href = '/login';
}
