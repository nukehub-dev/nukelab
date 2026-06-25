import confetti from 'canvas-confetti'

interface ConfettiOptions {
  particleCount?: number
  spread?: number
  origin?: { x?: number; y?: number }
  colors?: string[]
  duration?: number
}

export function celebrate(options: ConfettiOptions = {}) {
  const {
    particleCount = 100,
    spread = 70,
    origin = { y: 0.6 },
    colors = ['#a855f7', '#34d399', '#fbbf24', '#60a5fa', '#f87171'],
  } = options

  confetti({
    particleCount,
    spread,
    origin,
    colors,
    disableForReducedMotion: true,
    zIndex: 9999,
  })
}

export function celebrateSuccess() {
  celebrate({
    particleCount: 120,
    spread: 80,
    origin: { y: 0.7 },
    colors: ['#34d399', '#10b981', '#6ee7b7', '#a7f3d0'],
  })
}

export function celebrateDeploy() {
  const duration = 3000
  const animationEnd = Date.now() + duration
  const defaults = { startVelocity: 30, spread: 360, ticks: 60, zIndex: 9999 }

  const randomInRange = (min: number, max: number) => Math.random() * (max - min) + min

  const interval = setInterval(() => {
    const timeLeft = animationEnd - Date.now()

    if (timeLeft <= 0) {
      clearInterval(interval)
      return
    }

    const particleCount = 50 * (timeLeft / duration)

    confetti({
      ...defaults,
      particleCount,
      origin: { x: randomInRange(0.1, 0.3), y: Math.random() - 0.2 },
      colors: ['#a855f7', '#c084fc', '#e879f9', '#f0abfc'],
      disableForReducedMotion: true,
    })
    confetti({
      ...defaults,
      particleCount,
      origin: { x: randomInRange(0.7, 0.9), y: Math.random() - 0.2 },
      colors: ['#34d399', '#10b981', '#6ee7b7', '#a7f3d0'],
      disableForReducedMotion: true,
    })
  }, 250)
}

export function celebrateMilestone() {
  celebrate({
    particleCount: 200,
    spread: 100,
    origin: { y: 0.6 },
    colors: ['#fbbf24', '#f59e0b', '#fcd34d', '#fde68a', '#a855f7'],
  })
}
