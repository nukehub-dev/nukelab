import type { ApplicationTheme } from '../types/theme';

const DEFAULT_ACCENT = 'oklch(0.541 0.281 293.009)';

export function applyTheme(theme: ApplicationTheme): void {
  if (theme === 'default') {
    document.documentElement.removeAttribute('data-app-theme');
  } else {
    document.documentElement.setAttribute('data-app-theme', theme);
  }
}

export function applyDarkMode(isDark: boolean): void {
  document.documentElement.classList.toggle('dark', isDark);
  if (!isDark) {
    document.documentElement.classList.add('light');
  } else {
    document.documentElement.classList.remove('light');
  }
}

export function applyOledMode(isOled: boolean): void {
  document.documentElement.classList.toggle('oled', isOled);
}

export function applyAccentColor(color: string): void {
  const resolved = color === 'default' ? DEFAULT_ACCENT : color;

  document.documentElement.style.setProperty('--primary', resolved);
  document.documentElement.style.setProperty('--primary-foreground', getContrastingForeground(resolved));

  const ringColor = `color-mix(in srgb, ${resolved} 50%, transparent)`;
  document.documentElement.style.setProperty('--ring', ringColor);
  document.documentElement.style.setProperty('--sidebar-ring', ringColor);
}

function getColorBrightness(color: string): number {
  // Parse OKLCH to get lightness
  const match = color.match(/oklch\(([\d.]+)\s/);
  if (match) {
    return parseFloat(match[1]);
  }
  // Fallback for hex/rgb
  if (color.startsWith('#')) {
    const hex = color.replace('#', '');
    const r = parseInt(hex.substring(0, 2), 16) / 255;
    const g = parseInt(hex.substring(2, 4), 16) / 255;
    const b = parseInt(hex.substring(4, 6), 16) / 255;
    return 0.299 * r + 0.587 * g + 0.114 * b;
  }
  return 0.5;
}

function getContrastingForeground(color: string): string {
  const brightness = getColorBrightness(color);
  return brightness < 0.55 ? 'oklch(0.98 0 0)' : 'oklch(0.09 0 0)';
}
