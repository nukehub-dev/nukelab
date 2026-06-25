import { Link, useRouter } from '@tanstack/react-router'
import { ArrowLeft, Home } from 'lucide-react'
import { Button } from '../ui/button'
import { ReactorCore404 } from '../illustrations/reactor-core-404'
import { cn } from '../../lib/utils'

export function NotFound({ className }: { className?: string }) {
  const router = useRouter()

  return (
    <div
      className={cn(
        'fixed inset-0 z-50 flex flex-col items-center justify-center overflow-hidden bg-background/97 px-4 py-12 text-center backdrop-blur-sm',
        className
      )}
    >
      {/* Subtle ambient glow */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.06]"
        aria-hidden="true"
        style={{
          background: 'radial-gradient(circle at 50% 40%, var(--primary) 0%, transparent 50%)',
        }}
      />

      <div className="relative z-10 flex max-w-xl flex-col items-center">
        {/* Reactor illustration */}
        <div className="relative mb-2 flex h-56 w-56 items-center justify-center sm:h-72 sm:w-72">
          <ReactorCore404 className="h-full w-full" />
        </div>

        {/* 404 code */}
        <h1 className="bg-gradient-to-b from-foreground via-foreground to-muted-foreground bg-clip-text text-7xl font-extrabold tracking-tighter text-transparent sm:text-8xl">
          404
        </h1>

        <h2 className="mt-2 text-xl font-semibold tracking-tight text-foreground sm:text-2xl">
          Lost in the reactor
        </h2>
        <p className="mt-2 max-w-md text-sm text-muted-foreground sm:text-base">
          The magnetic containment field couldn't locate this page. It may have drifted into an
          unstable orbit.
        </p>

        {/* Actions */}
        <div className="mt-8 flex flex-col items-center gap-3 sm:flex-row">
          <Button variant="outline" size="lg" onClick={() => router.history.back()}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Go back
          </Button>
          <Link
            to="/"
            className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-primary px-6 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
          >
            <Home className="h-4 w-4" />
            Return to safe orbit
          </Link>
        </div>
      </div>
    </div>
  )
}
