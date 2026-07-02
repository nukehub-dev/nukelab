// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { motion } from 'framer-motion'
import { cn } from '../../lib/utils'

interface AmbientBackgroundProps {
  variant?: 'default' | 'dashboard' | 'subtle'
  className?: string
}

export function AmbientBackground({ variant = 'default', className }: AmbientBackgroundProps) {
  if (variant === 'subtle') return null

  return (
    <div className={cn('fixed inset-0 overflow-hidden pointer-events-none z-0', className)}>
      {/* Floating blobs */}
      <motion.div
        className="ambient-blob blob-1"
        style={{
          position: 'absolute',
          width: 400,
          height: 400,
          borderRadius: '50%',
          filter: 'blur(80px)',
          opacity: 0.15,
          background: 'var(--primary)',
          top: '10%',
          left: '10%',
        }}
        animate={{
          x: [0, 30, -20, 0],
          y: [0, -50, 20, 0],
          scale: [1, 1.1, 0.9, 1],
        }}
        transition={{
          duration: 20,
          repeat: Infinity,
          ease: 'easeInOut',
        }}
      />

      <motion.div
        className="ambient-blob blob-2"
        style={{
          position: 'absolute',
          width: 300,
          height: 300,
          borderRadius: '50%',
          filter: 'blur(80px)',
          opacity: 0.15,
          background: 'var(--chart-2)',
          bottom: '20%',
          right: '15%',
        }}
        animate={{
          x: [0, -40, 20, 0],
          y: [0, 30, -40, 0],
          scale: [1, 1.15, 0.95, 1],
        }}
        transition={{
          duration: 25,
          repeat: Infinity,
          ease: 'easeInOut',
        }}
      />

      {variant === 'dashboard' && (
        <>
          <motion.div
            style={{
              position: 'absolute',
              width: 250,
              height: 250,
              borderRadius: '50%',
              filter: 'blur(60px)',
              opacity: 0.1,
              background: 'var(--chart-3)',
              top: '50%',
              left: '50%',
            }}
            animate={{
              x: [0, 50, -30, 0],
              y: [0, -30, 50, 0],
              scale: [1, 1.2, 0.8, 1],
            }}
            transition={{
              duration: 18,
              repeat: Infinity,
              ease: 'easeInOut',
            }}
          />

          {/* Animated grid */}
          <div
            className="absolute inset-0 opacity-[0.02]"
            style={{
              backgroundImage: `
                linear-gradient(var(--border) 1px, transparent 1px),
                linear-gradient(90deg, var(--border) 1px, transparent 1px)
              `,
              backgroundSize: '40px 40px',
            }}
          />
        </>
      )}

      {/* Noise texture overlay */}
      <div
        className="absolute inset-0 opacity-[0.015] pointer-events-none"
        style={{
          backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E")`,
          mixBlendMode: 'overlay',
        }}
      />
    </div>
  )
}
