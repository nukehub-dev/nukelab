import type { ApplicationTheme, AccentColor } from '../types/theme'
import { ACCENT_COLORS } from '../types/theme'

const DEFAULT_ACCENT = 'oklch(0.541 0.281 293.009)'

export function applyTheme(theme: ApplicationTheme): void {
  if (theme === 'default') {
    document.documentElement.removeAttribute('data-app-theme')
  } else {
    document.documentElement.setAttribute('data-app-theme', theme)
  }
}

export function applyDarkMode(isDark: boolean): void {
  document.documentElement.classList.toggle('dark', isDark)
  if (!isDark) {
    document.documentElement.classList.add('light')
  } else {
    document.documentElement.classList.remove('light')
  }
}

export function applyOledMode(isOled: boolean): void {
  document.documentElement.classList.toggle('oled', isOled)
}

export function applyAccentColor(color: AccentColor): void {
  const accentDef = ACCENT_COLORS.find((c) => c.value === color)
  const resolved = accentDef ? accentDef.color : DEFAULT_ACCENT

  document.documentElement.style.setProperty('--primary', resolved)
  document.documentElement.style.setProperty(
    '--primary-foreground',
    getContrastingForeground(resolved)
  )

  const ringColor = `color-mix(in srgb, ${resolved} 50%, transparent)`
  document.documentElement.style.setProperty('--ring', ringColor)
  document.documentElement.style.setProperty('--sidebar-ring', ringColor)
}

function getContrastingForeground(_color: string): string {
  return 'oklch(0.98 0 0)'
}
