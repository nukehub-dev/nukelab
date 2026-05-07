export type ApplicationTheme =
  | 'default'
  | 'graphite'
  | 'ocean'
  | 'amber'
  | 'github'
  | 'nord'
  | 'everforest'
  | 'rosepine';

export const THEME_VALUES: ApplicationTheme[] = [
  'default', 'graphite', 'ocean', 'amber',
  'github', 'nord', 'everforest', 'rosepine'
];

export interface ThemePreview {
  light: { background: string; sidebar: string; card: string; border: string; foreground: string; primary: string };
  dark: { background: string; sidebar: string; card: string; border: string; foreground: string; primary: string };
}

export type AccentColor = 'default' | 'purple' | 'blue' | 'red' | 'green';

export const ACCENT_COLORS: { value: AccentColor; label: string; color: string }[] = [
  { value: 'default', label: 'Orange', color: 'oklch(0.70 0.18 55)' },
  { value: 'purple', label: 'Purple', color: 'oklch(0.627 0.233 303.896)' },
  { value: 'blue', label: 'Blue', color: 'oklch(0.773 0.127 231.134)' },
  { value: 'red', label: 'Red', color: 'oklch(0.608 0.209 27.019)' },
  { value: 'green', label: 'Green', color: 'oklch(0.65 0.17 145)' },
];

export const THEME_PREVIEWS: Record<ApplicationTheme, ThemePreview> = {
  default: {
    light: { background: '#fafafa', sidebar: '#f3f4f6', card: '#ffffff', border: '#d4d4d8', foreground: '#18181b', primary: '#8b5cf6' },
    dark: { background: '#24262b', sidebar: '#1c1f24', card: '#31343a', border: '#4a4f58', foreground: '#f5f7fa', primary: '#a855f7' }
  },
  graphite: {
    light: { background: '#f5f6f8', sidebar: '#ebedf0', card: '#ffffff', border: '#d1d5db', foreground: '#1f2937', primary: '#4b6bfb' },
    dark: { background: '#1a1d23', sidebar: '#14161a', card: '#252830', border: '#3a3f4a', foreground: '#e2e5e9', primary: '#5b7cfa' }
  },
  ocean: {
    light: { background: '#f0f9ff', sidebar: '#e0f2fe', card: '#ffffff', border: '#bae6fd', foreground: '#0c4a6e', primary: '#0ea5e9' },
    dark: { background: '#0f172a', sidebar: '#0b1120', card: '#1e293b', border: '#334155', foreground: '#e0f2fe', primary: '#38bdf8' }
  },
  amber: {
    light: { background: '#fefce8', sidebar: '#fef9c3', card: '#ffffff', border: '#fde047', foreground: '#422006', primary: '#eab308' },
    dark: { background: '#1c1917', sidebar: '#161412', card: '#292524', border: '#44403c', foreground: '#fef3c7', primary: '#fbbf24' }
  },
  github: {
    light: { background: '#ffffff', sidebar: '#f6f8fa', card: '#ffffff', border: '#d0d7de', foreground: '#1f2328', primary: '#0969da' },
    dark: { background: '#0d1117', sidebar: '#010409', card: '#161b22', border: '#30363d', foreground: '#c9d1d9', primary: '#58a6ff' }
  },
  nord: {
    light: { background: '#eceff4', sidebar: '#e5e9f0', card: '#ffffff', border: '#d8dee9', foreground: '#2e3440', primary: '#5e81ac' },
    dark: { background: '#2e3440', sidebar: '#242933', card: '#3b4252', border: '#434c5e', foreground: '#eceff4', primary: '#88c0d0' }
  },
  everforest: {
    light: { background: '#fdf6e3', sidebar: '#eee8d5', card: '#ffffff', border: '#d5c4a1', foreground: '#3c3836', primary: '#689d6a' },
    dark: { background: '#2b3339', sidebar: '#232a2e', card: '#374145', border: '#4a555b', foreground: '#d3c6aa', primary: '#a7c080' }
  },
  rosepine: {
    light: { background: '#faf4ed', sidebar: '#f2e9e1', card: '#ffffff', border: '#dfdad9', foreground: '#575279', primary: '#907aa9' },
    dark: { background: '#191724', sidebar: '#13111f', card: '#26233a', border: '#403d52', foreground: '#e0def4', primary: '#c4a7e7' }
  }
};
