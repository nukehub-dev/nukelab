import { createFileRoute, useNavigate } from '@tanstack/react-router';
import { motion } from 'framer-motion';
import { Command, LogIn, AlertCircle, ExternalLink } from 'lucide-react';
import { useState, useEffect } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '/api';

interface AuthMethod {
  type: string;
  name: string;
  enabled: boolean;
}

interface AuthMethodsResponse {
  methods: AuthMethod[];
  auth_mode: string;
  oauth_enabled: boolean;
}

export const Route = createFileRoute('/login')({
  component: LoginPage,
});

function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [authMethods, setAuthMethods] = useState<AuthMethod[]>([]);
  const [authConfig, setAuthConfig] = useState<AuthMethodsResponse | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const navigate = useNavigate();

  // Check for OAuth token in URL
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    const urlError = params.get('error');
    
    if (urlError) {
      setError(decodeURIComponent(urlError));
      // Clean URL
      window.history.replaceState({}, '', '/login');
    }
    
    if (token) {
      localStorage.setItem('nukelab-token', token);
      document.cookie = `nukelab_token=${token}; path=/; SameSite=Lax`;
      navigate({ to: '/' });
    }
  }, [navigate]);

  // Fetch available auth methods
  useEffect(() => {
    const fetchAuthMethods = async () => {
      try {
        const response = await fetch(`${API_BASE}/auth/methods`);
        if (response.ok) {
          const data = await response.json();
          setAuthMethods(data.methods || []);
          setAuthConfig(data);
        }
      } catch (err) {
        console.error('Failed to fetch auth methods:', err);
      } finally {
        setAuthLoading(false);
      }
    };

    fetchAuthMethods();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const formData = new URLSearchParams();
      formData.append('username', username);
      formData.append('password', password);

      const response = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: formData.toString(),
      });

      const responseText = await response.text();
      let data;
      try {
        data = JSON.parse(responseText);
      } catch {
        throw new Error(responseText || `Login failed (${response.status})`);
      }

      if (!response.ok) {
        throw new Error(data.detail || data.message || 'Login failed');
      }

      localStorage.setItem('nukelab-token', data.access_token);
      
      // Set cookie for server nginx auth (must match backend cookie name)
      document.cookie = `nukelab_token=${data.access_token}; path=/; SameSite=Lax`;
      
      // Navigate to dashboard after login
      navigate({ to: '/' });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  const handleOAuthLogin = () => {
    window.location.href = `${API_BASE}/auth/oauth/login`;
  };

  const hasLocalAuth = authMethods.some(m => m.type === 'local');
  const hasOAuth = authMethods.some(m => m.type === 'oauth');
  const showBoth = hasLocalAuth && hasOAuth;

  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
        >
          <Command className="w-8 h-8 text-primary" />
        </motion.div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-1/4 left-1/4 w-[500px] h-[500px] rounded-full bg-primary/5 blur-[100px] blob-float" />
        <div className="absolute bottom-1/4 right-1/4 w-[400px] h-[400px] rounded-full bg-chart-2/5 blur-[100px] blob-float" style={{ animationDelay: '-8s' }} />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 30, scale: 0.95 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ type: 'spring', stiffness: 120, damping: 14 }}
        className="w-full max-w-md"
      >
        <div className="bubble p-8 space-y-6">
          <div className="text-center space-y-2">
            <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-primary mb-4">
              <Command className="w-6 h-6 text-primary-foreground" />
            </div>
            <h1 className="text-2xl font-bold">Welcome back</h1>
            <p className="text-muted-foreground">
              {authConfig?.auth_mode === 'oauth' 
                ? 'Sign in with your organization account'
                : 'Sign in to your NukeLab account'
              }
            </p>
          </div>

          {error && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex items-center gap-2 p-3 rounded-lg bg-destructive/10 text-destructive text-sm"
            >
              <AlertCircle className="w-4 h-4 shrink-0" />
              {error}
            </motion.div>
          )}

          {hasOAuth && (
            <button
              onClick={handleOAuthLogin}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-secondary text-secondary-foreground font-medium text-sm hover:bg-secondary/80 hover:-translate-y-[1px] active:translate-y-[1px] transition-all duration-100"
            >
              <ExternalLink className="w-4 h-4" />
              Sign in with {authConfig?.oauth_enabled ? (authMethods.find(m => m.type === 'oauth')?.name || 'OAuth') : 'OAuth'}
            </button>
          )}

          {showBoth && (
            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t border-border" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-card px-2 text-muted-foreground">Or continue with</span>
              </div>
            </div>
          )}

          {hasLocalAuth && (
            <form className="space-y-4" onSubmit={handleSubmit}>
              <div className="space-y-2">
                <label className="text-sm font-medium">Username</label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Enter your username"
                  required
                  className="w-full px-3 py-2 rounded-lg bg-input/80 border border-border text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-[3px] focus:ring-ring/50 transition-all"
                />
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium">Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  required
                  className="w-full px-3 py-2 rounded-lg bg-input/80 border border-border text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-[3px] focus:ring-ring/50 transition-all"
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-primary text-primary-foreground font-medium text-sm hover:bg-primary/90 hover:brightness-110 hover:-translate-y-[1px] active:translate-y-[1px] transition-all duration-100 disabled:opacity-50 disabled:pointer-events-none"
              >
                {loading ? (
                  <motion.span
                    animate={{ rotate: 360 }}
                    transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
                    className="inline-block"
                  >
                    <LogIn className="w-4 h-4" />
                  </motion.span>
                ) : (
                  <>
                    <LogIn className="w-4 h-4" />
                    Sign In
                  </>
                )}
              </button>
            </form>
          )}

          <p className="text-center text-sm text-muted-foreground">
            Don't have an account?{' '}
            <span className="text-primary">Contact your administrator</span>
          </p>
        </div>
      </motion.div>
    </div>
  );
}
