import { Component, type ReactNode } from 'react';
import { motion } from 'framer-motion';
import { AlertTriangle, RefreshCw, Home } from 'lucide-react';
import { Button } from '../ui/button';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: string | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, errorInfo: null };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo);
    this.setState({ errorInfo: errorInfo.componentStack || null });
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
    window.location.reload();
  };

  handleGoHome = () => {
    window.location.href = '/';
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ type: 'spring', stiffness: 200, damping: 20 }}
          className="flex min-h-screen items-center justify-center p-4"
        >
          <div className="bubble max-w-md w-full p-8 text-center space-y-6">
            <motion.div
              initial={{ rotate: 0 }}
              animate={{ rotate: [0, -10, 10, -10, 10, 0] }}
              transition={{ duration: 0.5, delay: 0.2 }}
              className="mx-auto w-16 h-16 rounded-full bg-destructive/10 flex items-center justify-center"
            >
              <AlertTriangle className="w-8 h-8 text-destructive" />
            </motion.div>

            <div className="space-y-2">
              <h1 className="text-xl font-bold">Something went wrong</h1>
              <p className="text-sm text-muted-foreground">
                We encountered an unexpected error. Our team has been notified.
              </p>
            </div>

            {this.state.error && (
              <div className="rounded-md bg-muted/50 p-3 text-left overflow-auto max-h-32">
                <code className="text-xs font-mono text-destructive">
                  {this.state.error.toString()}
                </code>
              </div>
            )}

            <div className="flex gap-3 justify-center">
              <Button onClick={this.handleReset} variant="outline" className="gap-2">
                <RefreshCw className="w-4 h-4" />
                Reload
              </Button>
              <Button onClick={this.handleGoHome} variant="default" className="gap-2">
                <Home className="w-4 h-4" />
                Go Home
              </Button>
            </div>
          </div>
        </motion.div>
      );
    }

    return this.props.children;
  }
}

// Route-level error boundary wrapper
export function RouteErrorBoundary() {
  return (
    <ErrorBoundary>
      <div className="p-8 text-center">
        <AlertTriangle className="w-12 h-12 text-destructive mx-auto mb-4" />
        <h2 className="text-lg font-semibold mb-2">Failed to load page</h2>
        <p className="text-sm text-muted-foreground">
          There was an error loading this page. Please try again.
        </p>
      </div>
    </ErrorBoundary>
  );
}
