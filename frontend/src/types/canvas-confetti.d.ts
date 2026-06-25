declare module 'canvas-confetti' {
  interface ConfettiOptions {
    particleCount?: number
    spread?: number
    origin?: { x?: number; y?: number }
    colors?: string[]
    disableForReducedMotion?: boolean
    zIndex?: number
    startVelocity?: number
    ticks?: number
    gravity?: number
    scalar?: number
    drift?: number
  }

  function confetti(options?: ConfettiOptions): Promise<null>

  export = confetti
}
