import { createFileRoute, useNavigate } from '@tanstack/react-router';
import { motion, AnimatePresence } from 'framer-motion';
import { LogIn, AlertCircle, ExternalLink, Cloud, Wrench, Users, Eye, EyeOff, Loader2 } from 'lucide-react';
import { useState, useEffect } from 'react';
import { NukeLabLogo } from '../components/logo';

const API_BASE = import.meta.env.VITE_API_URL || '/api';

interface AuthMethod {
  type: string;
  name: string;
  enabled: boolean;
}



const features = [
  { icon: Cloud, title: 'Cloud Simulations', desc: 'Run nuclear physics simulations in your browser with zero setup.' },
  { icon: Wrench, title: 'Full Toolset', desc: 'Geant4, OpenMC, PyNE, and more pre-installed and ready.' },
  { icon: Users, title: 'Collaboration', desc: 'Share workspaces, co-edit notebooks, and publish results.' },
];

export const Route = createFileRoute('/login')({
  component: LoginPage,
});

function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPass, setShowPass] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [authMethods, setAuthMethods] = useState<AuthMethod[]>([]);
  const [authLoading, setAuthLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    const refresh = params.get('refresh');
    const errMsg = params.get('error');
    if (errMsg) { setError(decodeURIComponent(errMsg)); window.history.replaceState({}, '', '/login'); }
    if (token) {
      localStorage.setItem('nukelab-token', token);
      if (refresh) localStorage.setItem('nukelab-refresh', refresh);
      document.cookie = `nukelab_token=${token}; path=/; SameSite=Lax`;
      navigate({ to: '/' });
    }
  }, [navigate]);

  useEffect(() => {
    fetch(`${API_BASE}/auth/methods`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) { setAuthMethods(d.methods || []); } })
      .catch(() => {})
      .finally(() => setAuthLoading(false));
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const fd = new URLSearchParams();
      fd.append('username', username);
      fd.append('password', password);
      const res = await fetch(`${API_BASE}/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: fd.toString() });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || 'Login failed');
      localStorage.setItem('nukelab-token', data.access_token);
      if (data.refresh_token) localStorage.setItem('nukelab-refresh', data.refresh_token);
      document.cookie = `nukelab_token=${data.access_token}; path=/; SameSite=Lax`;
      navigate({ to: '/' });
    } catch (err: any) {
      setError(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  const handleOAuth = () => { window.location.href = `${API_BASE}/auth/oauth/login`; };
  const hasLocal = authMethods.some(m => m.type === 'local');
  const hasOAuth = authMethods.some(m => m.type === 'oauth');

  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <motion.div animate={{ rotate: 360 }} transition={{ duration: 2, repeat: Infinity, ease: 'linear' }}>
          <NukeLabLogo size={48} className="text-primary" />
        </motion.div>
      </div>
    );
  }

  return (
    <div className="min-h-screen relative overflow-hidden bg-background">
      {/* ── Ambient Background ── */}
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute inset-0 bg-gradient-to-br from-primary/[0.03] via-transparent to-chart-2/[0.03]" />
        <motion.div className="absolute top-[-10%] left-[-10%] w-[50vw] h-[50vw] rounded-full bg-primary/[0.04] blur-[120px]"
          animate={{ x: [0, 30, 0], y: [0, -20, 0], scale: [1, 1.1, 1] }} transition={{ duration: 12, repeat: Infinity, ease: 'easeInOut' }} />
        <motion.div className="absolute bottom-[-10%] right-[-10%] w-[40vw] h-[40vw] rounded-full bg-chart-2/[0.04] blur-[120px]"
          animate={{ x: [0, -20, 0], y: [0, 30, 0], scale: [1.1, 1, 1.1] }} transition={{ duration: 15, repeat: Infinity, ease: 'easeInOut', delay: 3 }} />
        <motion.div className="absolute top-[40%] left-[50%] w-[30vw] h-[30vw] rounded-full bg-primary/[0.02] blur-[100px]"
          animate={{ scale: [1, 1.2, 1], opacity: [0.3, 0.6, 0.3] }} transition={{ duration: 10, repeat: Infinity, ease: 'easeInOut', delay: 5 }} />
        {/* Dot grid pattern */}
        <div className="absolute inset-0 opacity-[0.03]" style={{ backgroundImage: 'radial-gradient(circle, currentColor 1px, transparent 1px)', backgroundSize: '32px 32px' }} />
      </div>

      {/* ── Mobile Layout: Centered Login ── */}
      <div className="lg:hidden relative z-10 flex flex-col items-center justify-center min-h-screen px-6 py-8">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="flex flex-col items-center gap-3 mb-8"
        >
          <div className="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center ring-1 ring-primary/20">
            <NukeLabLogo size={40} className="text-primary" />
          </div>
          <div className="text-center">
            <h1 className="text-2xl font-bold tracking-tight">NukeLab</h1>
            <p className="text-sm text-muted-foreground mt-1">Your Nuclear Simulation Workspace</p>
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ type: 'spring', stiffness: 100, damping: 15, delay: 0.2 }}
          className="w-full max-w-sm"
        >
          <LoginCard 
            error={error} 
            hasLocal={hasLocal} 
            hasOAuth={hasOAuth} 
            authMethods={authMethods}
            handleOAuth={handleOAuth}
            handleSubmit={handleSubmit}
            username={username}
            setUsername={setUsername}
            password={password}
            setPassword={setPassword}
            showPass={showPass}
            setShowPass={setShowPass}
            loading={loading}
          />
        </motion.div>

        {/* Features on mobile */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.5, duration: 0.6 }}
          className="w-full max-w-sm mt-8 space-y-3"
        >
          <p className="text-center text-xs text-muted-foreground uppercase tracking-wider font-medium mb-4">
            Platform Features
          </p>
          {features.map((f, i) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ 
                delay: 0.5 + i * 0.1,
                type: 'spring',
                stiffness: 300,
                damping: 24
              }}
              className="flex items-start gap-3 p-3 rounded-xl bg-card/30 border border-border/30 backdrop-blur-sm"
            >
              <div className="flex-shrink-0 w-9 h-9 rounded-lg bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center">
                <f.icon className="w-4 h-4 text-primary" />
              </div>
              <div className="pt-0.5">
                <h3 className="font-semibold text-sm">{f.title}</h3>
                <p className="text-xs text-muted-foreground/80 leading-relaxed">{f.desc}</p>
              </div>
            </motion.div>
          ))}
        </motion.div>
      </div>

      {/* ── Desktop Layout: Split ── */}
      <div className="hidden lg:flex min-h-screen">
        {/* ── Left Panel ── */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8 }}
          className="relative z-10 flex-1 flex flex-col justify-center px-16 xl:px-24 max-w-[55%]"
        >
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2, duration: 0.6 }}
            className="flex items-center gap-4 mb-10"
          >
            <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center ring-1 ring-primary/20">
              <NukeLabLogo size={28} className="text-primary" />
            </div>
            <h1 className="text-[28px] font-bold tracking-tight leading-none">NukeLab</h1>
          </motion.div>

          <motion.h2
            initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3, duration: 0.6 }}
            className="text-5xl xl:text-6xl font-bold leading-[1.1] mb-6"
          >
            Your Nuclear Simulation{' '}
            <span className="bg-gradient-to-r from-primary to-chart-2 bg-clip-text text-transparent">Workspace</span>
          </motion.h2>

          <motion.p
            initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4, duration: 0.6 }}
            className="text-lg text-muted-foreground mb-12 max-w-xl leading-relaxed"
          >
            Access NukeIDE, run simulations in isolated containers, and collaborate with your team. 
            Everything you need for computational nuclear engineering in one place.
          </motion.p>

          <div className="space-y-3 max-w-lg">
            {features.map((f, i) => (
              <motion.div
                key={f.title}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ 
                  delay: 0.3 + i * 0.08,
                  type: 'spring',
                  stiffness: 300,
                  damping: 24
                }}
                whileHover={{ 
                  scale: 1.02,
                  transition: { type: 'spring', stiffness: 400, damping: 17 }
                }}
                className="group flex items-start gap-4 p-4 rounded-xl bg-card/30 border border-border/30 backdrop-blur-sm hover:bg-card/50 hover:border-primary/30 transition-colors cursor-default"
              >
                <div className="flex-shrink-0 w-10 h-10 rounded-xl bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center group-hover:from-primary/30 group-hover:to-primary/10 transition-all duration-300 shadow-sm shadow-primary/5 group-hover:shadow-md group-hover:shadow-primary/10">
                  <f.icon className="w-5 h-5 text-primary group-hover:scale-110 transition-transform duration-300" />
                </div>
                <div className="pt-0.5">
                  <h3 className="font-semibold text-sm mb-1 group-hover:text-primary transition-colors duration-300">{f.title}</h3>
                  <p className="text-xs text-muted-foreground/80 leading-relaxed">{f.desc}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </motion.div>

        {/* ── Right Panel ── */}
        <div className="relative z-10 flex-1 flex items-center justify-center px-8">
          <motion.div
            initial={{ opacity: 0, y: 40, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ type: 'spring', stiffness: 100, damping: 15, delay: 0.3 }}
            className="w-full max-w-[420px]"
          >
            <LoginCard 
              error={error} 
              hasLocal={hasLocal} 
              hasOAuth={hasOAuth} 
              authMethods={authMethods}
              handleOAuth={handleOAuth}
              handleSubmit={handleSubmit}
              username={username}
              setUsername={setUsername}
              password={password}
              setPassword={setPassword}
              showPass={showPass}
              setShowPass={setShowPass}
              loading={loading}
            />
          </motion.div>
        </div>
      </div>
    </div>
  );
}

interface LoginCardProps {
  error: string;
  hasLocal: boolean;
  hasOAuth: boolean;
  authMethods: AuthMethod[];
  handleOAuth: () => void;
  handleSubmit: (e: React.FormEvent) => void;
  username: string;
  setUsername: (v: string) => void;
  password: string;
  setPassword: (v: string) => void;
  showPass: boolean;
  setShowPass: (v: boolean) => void;
  loading: boolean;
}

function LoginCard({ error, hasLocal, hasOAuth, authMethods, handleOAuth, handleSubmit, username, setUsername, password, setPassword, showPass, setShowPass, loading }: LoginCardProps) {
  const showBoth = hasLocal && hasOAuth;
  
  return (
    <div className="relative rounded-2xl border border-border/50 bg-card/60 backdrop-blur-xl shadow-2xl shadow-black/20 overflow-hidden">
      {/* Card top glow */}
      <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-primary/30 to-transparent" />
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-32 h-16 bg-primary/10 blur-2xl rounded-full" />

      <div className="relative p-8 space-y-6">
        {/* Header */}
        <div className="text-center space-y-1">
          <h2 className="text-xl font-bold">Sign In</h2>
          <p className="text-sm text-muted-foreground">
            Access your workspace
          </p>
        </div>

        {/* Error */}
        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="flex items-center gap-2 p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-sm"
            >
              <AlertCircle className="w-4 h-4 shrink-0" />
              {error}
            </motion.div>
          )}
        </AnimatePresence>

        {/* OAuth Only Mode */}
        {hasOAuth && !hasLocal && (
          <div className="space-y-4">
            <button
              onClick={handleOAuth}
              className="w-full flex items-center justify-center gap-3 px-6 py-3 rounded-xl bg-primary text-primary-foreground font-semibold text-base hover:bg-primary/90 active:scale-[0.98] transition-all duration-150 shadow-lg shadow-primary/25 hover:shadow-xl hover:shadow-primary/30 hover:-translate-y-0.5"
            >
              <ExternalLink className="w-5 h-5" />
              Sign in with {authMethods.find(m => m.type === 'oauth')?.name || 'OAuth'}
            </button>
            
            <p className="text-center text-xs text-muted-foreground/70 leading-relaxed">
              You'll be redirected to your organization's login page to authenticate securely.
            </p>
          </div>
        )}

        {/* Both or Local Only Mode */}
        {(hasLocal || showBoth) && (
          <>
            {/* OAuth (when both enabled) */}
            {hasOAuth && hasLocal && (
              <button
                onClick={handleOAuth}
                className="w-full flex items-center justify-center gap-2.5 px-4 py-2.5 rounded-lg bg-secondary hover:bg-secondary/80 border border-border/50 text-secondary-foreground font-medium text-sm active:scale-[0.98] transition-all duration-150 hover:-translate-y-0.5"
              >
                <ExternalLink className="w-4 h-4" />
                Sign in with {authMethods.find(m => m.type === 'oauth')?.name || 'OAuth'}
              </button>
            )}

            {/* Divider */}
            {showBoth && (
              <div className="relative">
                <div className="absolute inset-0 flex items-center"><span className="w-full border-t border-border/50" /></div>
                <div className="relative flex justify-center text-[10px] uppercase tracking-wider">
                  <span className="bg-card px-3 text-muted-foreground font-medium">or continue with email</span>
                </div>
              </div>
            )}

            {/* Local Form */}
            {hasLocal && (
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Username</label>
                  <div className="relative group">
                    <input
                      type="text"
                      value={username}
                      onChange={e => setUsername(e.target.value)}
                      placeholder="Enter your username"
                      required
                      className="w-full px-3.5 py-2.5 rounded-lg bg-input/60 border border-border/60 text-sm placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-all group-hover:border-border"
                    />
                  </div>
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Password</label>
                  <div className="relative group">
                    <input
                      type={showPass ? 'text' : 'password'}
                      value={password}
                      onChange={e => setPassword(e.target.value)}
                      placeholder="••••••••"
                      required
                      className="w-full px-3.5 py-2.5 pr-10 rounded-lg bg-input/60 border border-border/60 text-sm placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-all group-hover:border-border"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPass(!showPass)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground/60 hover:text-muted-foreground transition-colors p-0.5"
                      tabIndex={-1}
                    >
                      {showPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-primary text-primary-foreground font-medium text-sm hover:bg-primary/90 active:scale-[0.98] transition-all duration-150 disabled:opacity-50 disabled:pointer-events-none shadow-lg shadow-primary/20 hover:-translate-y-0.5"
                >
                  {loading ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <>
                      <LogIn className="w-4 h-4" />
                      Sign In
                    </>
                  )}
                </button>
              </form>
            )}

            {/* Only show for local auth */}
            {hasLocal && (
              <p className="text-center text-xs text-muted-foreground pt-2">
                Don't have an account?{' '}
                <span className="text-primary font-medium hover:underline">Contact your administrator</span>
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
