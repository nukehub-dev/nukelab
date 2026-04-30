import { createFileRoute } from '@tanstack/react-router';
import { motion } from 'framer-motion';
import { Command, LogIn } from 'lucide-react';
import { useState } from 'react';

export const Route = createFileRoute('/login')({
  component: LoginPage,
});

function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

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
            <p className="text-muted-foreground">Sign in to your NukeLab account</p>
          </div>

          <form className="space-y-4" onSubmit={(e) => e.preventDefault()}>
            <div className="space-y-2">
              <label className="text-sm font-medium">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
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
                className="w-full px-3 py-2 rounded-lg bg-input/80 border border-border text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-[3px] focus:ring-ring/50 transition-all"
              />
            </div>

            <button
              type="submit"
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-primary text-primary-foreground font-medium text-sm hover:bg-primary/90 active:scale-[0.98] transition-all duration-200"
            >
              <LogIn className="w-4 h-4" />
              Sign In
            </button>
          </form>

          <p className="text-center text-sm text-muted-foreground">
            Don't have an account?{' '}
            <button className="text-primary hover:underline">Contact your administrator</button>
          </p>
        </div>
      </motion.div>
    </div>
  );
}
