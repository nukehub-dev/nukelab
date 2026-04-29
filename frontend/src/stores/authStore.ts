import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface User {
  id: string;
  username: string;
  email: string;
  full_name: string | null;
  role: string;
  credit_balance: number;
  is_active: boolean;
}

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  isHydrated: boolean;
  
  // Actions
  setUser: (user: Partial<User>) => void;
  setToken: (token: string) => void;
  setError: (error: string | null) => void;
  setLoading: (loading: boolean) => void;
  login: (token: string, user: User) => void;
  logout: () => void;
  
  // Computed
  isAdmin: () => boolean;
  isSuperAdmin: () => boolean;
}

// Cookie helpers
const setCookie = (token: string) => {
  if (typeof document !== 'undefined') {
    document.cookie = `nukelab_token=${token}; path=/; max-age=86400; SameSite=Lax`;
  }
};

const clearCookie = () => {
  if (typeof document !== 'undefined') {
    document.cookie = 'nukelab_token=; path=/; max-age=0; SameSite=Lax';
  }
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,
      isHydrated: false,
      
      setUser: (user) => set((state) => ({
        user: state.user ? { ...state.user, ...user } : (user as User)
      })),
      
      setToken: (token) => {
        setCookie(token);
        set({ token });
      },
      
      setError: (error) => set({ error }),
      setLoading: (loading) => set({ isLoading: loading }),
      
      login: (token, user) => {
        setCookie(token);
        set({
          token,
          user,
          isAuthenticated: true,
          error: null,
          isLoading: false
        });
      },
      
      logout: () => {
        clearCookie();
        set({
          user: null,
          token: null,
          isAuthenticated: false,
          error: null,
          isLoading: false
        });
      },
      
      isAdmin: () => {
        const { user } = get();
        return user?.role === 'admin' || user?.role === 'super_admin';
      },
      
      isSuperAdmin: () => {
        const { user } = get();
        return user?.role === 'super_admin';
      }
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({ 
        user: state.user, 
        isAuthenticated: state.isAuthenticated,
        token: state.token
      }),
      onRehydrateStorage: () => (state) => {
        if (state) {
          state.isHydrated = true;
        }
      }
    }
  )
);
