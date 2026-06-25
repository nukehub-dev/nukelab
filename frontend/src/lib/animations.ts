import { type Transition, type Spring } from 'framer-motion'

// Duration tokens
export const duration = {
  instant: 0.05,
  fast: 0.15,
  normal: 0.3,
  slow: 0.5,
  slower: 0.8,
} as const

// Easing tokens
export const ease = {
  default: [0.4, 0, 0.2, 1] as const,
  in: [0.4, 0, 1, 1] as const,
  out: [0, 0, 0.2, 1] as const,
  spring: [0.34, 1.56, 0.64, 1] as const,
  smooth: [0.45, 0.05, 0.55, 0.95] as const,
  dramatic: [0.87, 0, 0.13, 1] as const,
} as const

// Spring physics
export const springs = {
  gentle: { type: 'spring' as const, stiffness: 120, damping: 14 },
  bouncy: { type: 'spring' as const, stiffness: 300, damping: 10 },
  stiff: { type: 'spring' as const, stiffness: 400, damping: 30 },
  slow: { type: 'spring' as const, stiffness: 80, damping: 20 },
  wobble: { type: 'spring' as const, stiffness: 180, damping: 12 },
} as const

// Stagger delays
export const stagger = {
  fast: 0.03,
  normal: 0.06,
  slow: 0.1,
  cascade: 0.08,
} as const

// Page transition variants
export const pageTransition: Transition = {
  duration: duration.slow,
  ease: [0.22, 1, 0.36, 1],
}

// Framer Motion variants
export const fadeInVariants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: duration.normal } },
}

export const slideUpVariants = {
  hidden: { opacity: 0, y: 30 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: duration.normal, ease: ease.out },
  },
}

export const scaleInVariants = {
  hidden: { opacity: 0, scale: 0.9 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: springs.gentle as Spring,
  },
}

export const staggerContainerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: stagger.normal, delayChildren: 0.1 },
  },
}

export const staggerItemVariants = {
  hidden: { opacity: 0, y: 30, scale: 0.95 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: springs.gentle as Spring,
  },
}

export const cardHoverVariants = {
  rest: { y: 0, boxShadow: '0 8px 24px -8px rgba(0,0,0,0.2)' },
  hover: {
    y: -4,
    boxShadow: '0 20px 40px -12px rgba(0,0,0,0.3)',
    transition: springs.gentle as Spring,
  },
}

export const modalOverlayVariants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: duration.fast } },
  exit: { opacity: 0, transition: { duration: duration.instant } },
}

export const modalContentVariants = {
  hidden: { opacity: 0, scale: 0.9, y: 20 },
  visible: {
    opacity: 1,
    scale: 1,
    y: 0,
    transition: { type: 'spring', stiffness: 300, damping: 25 },
  },
  exit: {
    opacity: 0,
    scale: 0.95,
    y: 10,
    transition: { duration: duration.fast },
  },
}

export const drawerVariants = {
  hidden: { x: '-100%' },
  visible: {
    x: 0,
    transition: { type: 'spring', stiffness: 300, damping: 30 },
  },
  exit: {
    x: '-100%',
    transition: { type: 'spring', stiffness: 300, damping: 30 },
  },
}

export const toastVariants = {
  hidden: { opacity: 0, y: -50, scale: 0.9 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { type: 'spring', stiffness: 400, damping: 25 },
  },
  exit: {
    opacity: 0,
    x: 100,
    transition: { duration: duration.normal },
  },
}
