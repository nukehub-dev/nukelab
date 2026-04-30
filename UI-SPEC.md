# NukeLab UI/UX Specification

**Version**: 2.0  
**Status**: Draft — Ready for Implementation  
**Stack**: Vite + React 19 + TanStack Router + TanStack Query + Tailwind CSS v4  
**Reference Design**: Arcane (Docker Management Platform)

---

## Table of Contents

1. [Design Philosophy](#1-design-philosophy)
2. [Technology Stack](#2-technology-stack)
3. [Design Tokens](#3-design-tokens)
4. [Theme System](#4-theme-system)
5. [Component Architecture](#5-component-architecture)
6. [Layout System](#6-layout-system)
7. [Data Visualization](#7-data-visualization)
8. [Animation & Motion](#8-animation--motion)
9. [Accessibility](#9-accessibility)
10. [Responsive Design](#10-responsive-design)
11. [File Structure](#11-file-structure)
12. [Implementation Roadmap](#12-implementation-roadmap)

---

## 1. Design Philosophy

### Core Principles

**Scientific Precision**: NukeLab is a technical platform for nuclear engineering simulations. The UI must communicate accuracy, reliability, and computational power. Every visual element should feel engineered, not decorative.

**Resource Consciousness**: With only 64GB RAM across the infrastructure, the backend must be lightweight. The frontend is a static Vite SPA — bundle size is not a runtime concern. We can afford rich animations, heavy libraries, and visual polish. The user experience is paramount.

**Data Density Over White Space**: Engineers need to see maximum information at a glance. Compact layouts, dense tables, and information-rich cards are preferred over airy, sparse designs.

**Real-Time Clarity**: Live metrics, container states, and resource usage must be immediately scannable. Color coding, status indicators, and trend visualizations are essential.

**Hardware Efficiency**: Zero server-side rendering. Static file deployment only. Minimal runtime JavaScript. Aggressive code splitting per route.

### Visual Direction

- **Glassmorphism** with subtle depth — floating cards with translucent backgrounds
- **Dark mode default** — reduces eye strain during long simulation monitoring sessions
- **OKLCH color space** — perceptually uniform colors that maintain accessibility
- **Geist typography** — excellent legibility at small sizes for dense data UIs
- **Semantic actions** — buttons colored by action type (start, stop, delete), not by hierarchy

---

## 2. Technology Stack

### Core Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `react` | ^19.0.0 | UI framework |
| `react-dom` | ^19.0.0 | DOM renderer |
| `vite` | ^6.0.0 | Build tool |
| `@tanstack/react-router` | ^1.0.0 | Type-safe routing |
| `@tanstack/react-query` | ^5.0.0 | Server state management |
| `tailwindcss` | ^4.0.0 | Utility-first CSS |
| `@tanstack/react-table` | ^8.0.0 | Data tables |
| `recharts` | ^2.0.0 | Charts (lightweight) |
| `lucide-react` | ^0.400.0 | Icons |
| `clsx` + `tailwind-merge` | latest | Class name utilities |
| `zustand` | ^5.0.0 | Client state (theme, sidebar) |
| `framer-motion` | ^11.0.0 | React animations, gestures, layouts |
| `gsap` | ^3.12.0 | Complex timelines, scroll animations |
| `@gsap/react` | ^2.0.0 | GSAP React hooks |
| `react-countup` | ^6.5.0 | Animated number counters |
| `canvas-confetti` | ^1.9.0 | Celebration effects |

### Why These Choices?

- **Vite over Next.js**: No SSR = no Node.js runtime = RAM saved for containers
- **TanStack Router**: Type-safe, file-based routing, data loading at route level
- **TanStack Query**: Automatic caching, polling, WebSocket integration, background refetching
- **Recharts over D3**: Simpler API, React-native, smaller bundle for standard charts
- **Zustand over Redux**: Minimal boilerplate, tiny bundle, perfect for UI state

---

## 3. Design Tokens

### 3.1 Color System (OKLCH)

All colors use **OKLCH** for perceptual uniformity. This ensures that changing themes doesn't break contrast ratios and that color adjustments (lighten/darken) behave predictably.

#### Base Tokens

```css
:root {
  --radius: 0.65rem;
  
  /* Semantic Colors */
  --background: oklch(0.141 0.005 285.823);
  --foreground: oklch(0.985 0 0);
  --card: oklch(0.21 0.006 285.885 / 0.6);
  --card-foreground: oklch(0.985 0 0);
  --popover: oklch(0.21 0.006 285.885);
  --popover-foreground: oklch(0.985 0 0);
  
  /* Primary — Dynamic based on accent */
  --primary: oklch(0.541 0.281 293.009);
  --primary-foreground: oklch(0.969 0.016 293.756);
  
  /* Secondary */
  --secondary: oklch(0.274 0.006 286.033 / 0.55);
  --secondary-foreground: oklch(0.985 0 0);
  
  /* Muted */
  --muted: oklch(0.274 0.006 286.033 / 0.55);
  --muted-foreground: oklch(0.705 0.015 286.067);
  
  /* Accent */
  --accent: oklch(0.274 0.006 286.033 / 0.55);
  --accent-foreground: oklch(0.985 0 0);
  
  /* Destructive */
  --destructive: oklch(0.704 0.191 22.216);
  --destructive-foreground: oklch(0.985 0 0);
  
  /* Borders & Inputs */
  --border: oklch(1 0 0 / 10%);
  --input: oklch(1 0 0 / 15%);
  --ring: oklch(0.541 0.281 293.009);
  
  /* Charts */
  --chart-1: oklch(0.488 0.243 264.376);
  --chart-2: oklch(0.696 0.17 162.48);
  --chart-3: oklch(0.769 0.188 70.08);
  --chart-4: oklch(0.627 0.265 303.9);
  --chart-5: oklch(0.645 0.246 16.439);
  
  /* Sidebar */
  --sidebar: oklch(0.21 0.006 285.885 / 0.6);
  --sidebar-foreground: oklch(0.985 0 0);
  --sidebar-primary: oklch(0.541 0.281 293.009);
  --sidebar-primary-foreground: oklch(0.969 0.016 293.756);
  --sidebar-accent: oklch(0.274 0.006 286.033 / 0.55);
  --sidebar-accent-foreground: oklch(0.985 0 0);
  --sidebar-border: oklch(1 0 0 / 10%);
  --sidebar-ring: oklch(0.541 0.281 293.009);
  
  /* Surface & Glass */
  --surface: oklch(0.21 0.006 285.885);
  --bg-surface: var(--surface);
  --glass-base: var(--bg-surface);
  --glass-tint: var(--primary);
  --glass-shadow-color: oklch(0 0 0 / 0.32);
  --glass-noise-opacity: 0.03;
}
```

#### Status Colors (Fixed Across Themes)

| Status | Light | Dark | Usage |
|--------|-------|------|-------|
| **Running** | `#10b981` | `#34d399` | Active containers |
| **Stopped** | `#6b7280` | `#9ca3af` | Inactive containers |
| **Error** | `#ef4444` | `#f87171` | Failed operations |
| **Warning** | `#f59e0b` | `#fbbf24` | Resource limits |
| **Pending** | `#3b82f6` | `#60a5fa` | Creating/starting |
| **Info** | `#0ea5e9` | `#38bdf8` | Informational |

### 3.2 Typography

#### Font Stack

```css
@font-face {
  font-family: 'Geist';
  src: url('/fonts/GeistVariable.woff2') format('woff2');
  font-weight: 100 900;
  font-display: swap;
  font-style: normal;
}

@font-face {
  font-family: 'Geist Mono';
  src: url('/fonts/GeistMonoVariable.woff2') format('woff2');
  font-weight: 100 900;
  font-display: swap;
  font-style: normal;
}
```

#### Type Scale

| Token | Size | Weight | Line Height | Usage |
|-------|------|--------|-------------|-------|
| `display` | 2.5rem (40px) | 700 | 1.1 | Page titles |
| `h1` | 1.875rem (30px) | 700 | 1.2 | Section headers |
| `h2` | 1.5rem (24px) | 600 | 1.3 | Card titles |
| `h3` | 1.25rem (20px) | 600 | 1.4 | Subsection |
| `body` | 0.875rem (14px) | 400 | 1.5 | Body text |
| `small` | 0.75rem (12px) | 400 | 1.5 | Captions, metadata |
| `xs` | 0.625rem (10px) | 500 | 1.4 | Badges, labels |

#### Font Features

```css
body {
  font-family: 'Geist', system-ui, -apple-system, sans-serif;
  -webkit-font-smoothing: auto;
  -moz-osx-font-smoothing: auto;
  text-rendering: optimizeLegibility;
}

.font-mono {
  font-family: 'Geist Mono', 'Fira Code', monospace;
  font-variant-ligatures: none;
  font-feature-settings: 'liga' 0, 'clig' 0;
}
```

### 3.3 Spacing Scale

Base unit: **4px**

| Token | Value | Usage |
|-------|-------|-------|
| `space-1` | 4px | Icon gaps, tight padding |
| `space-2` | 8px | Inline spacing |
| `space-3` | 12px | Component padding |
| `space-4` | 16px | Card padding |
| `space-5` | 20px | Section gaps |
| `space-6` | 24px | Page sections |
| `space-8` | 32px | Major sections |
| `space-10` | 40px | Page margins |

### 3.4 Border Radius

| Token | Value | Usage |
|-------|-------|-------|
| `radius-sm` | 4px | Buttons, inputs |
| `radius-md` | 8px | Small cards |
| `radius-lg` | 12px | Cards, modals |
| `radius-xl` | 16px | Large cards, panels |
| `radius-2xl` | 20px | Feature cards |
| `radius-full` | 9999px | Pills, avatars |

### 3.5 Shadows

```css
/* Context-aware shadows using color-mix */
.shadow-bubble {
  box-shadow:
    0 8px 24px -8px color-mix(in oklch, var(--glass-shadow-color) 70%, transparent),
    0 1px 0 0 color-mix(in oklch, var(--glass-base) 30%, transparent) inset;
}

.shadow-bubble-lg {
  box-shadow:
    0 14px 40px -14px color-mix(in oklch, var(--glass-shadow-color) 80%, transparent),
    0 1px 0 0 color-mix(in oklch, var(--glass-base) 35%, transparent) inset;
}

.shadow-float {
  box-shadow: 0 4px 20px -4px color-mix(in oklch, var(--glass-shadow-color) 60%, transparent);
}
```

### 3.6 Animation Tokens

#### Duration Scale

| Token | Value | Usage |
|-------|-------|-------|
| `duration-instant` | 50ms | Micro-feedback (color changes) |
| `duration-fast` | 150ms | Button presses, focus rings |
| `duration-normal` | 300ms | Standard transitions, hovers |
| `duration-slow` | 500ms | Page transitions, modals |
| `duration-slower` | 800ms | Complex entrances, celebrations |

#### Easing Functions

| Token | Value | Usage |
|-------|-------|-------|
| `ease-default` | `cubic-bezier(0.4, 0, 0.2, 1)` | Standard transitions |
| `ease-in` | `cubic-bezier(0.4, 0, 1, 1)` | Exit animations |
| `ease-out` | `cubic-bezier(0, 0, 0.2, 1)` | Entrance animations |
| `ease-spring` | `cubic-bezier(0.34, 1.56, 0.64, 1)` | Bouncy interactions |
| `ease-smooth` | `cubic-bezier(0.45, 0.05, 0.55, 0.95)` | Ambient motion |
| `ease-dramatic` | `cubic-bezier(0.87, 0, 0.13, 1)` | Page transitions |

#### Spring Physics (Framer Motion)

```typescript
const springs = {
  gentle: { type: 'spring', stiffness: 120, damping: 14 },
  bouncy: { type: 'spring', stiffness: 300, damping: 10 },
  stiff: { type: 'spring', stiffness: 400, damping: 30 },
  slow: { type: 'spring', stiffness: 80, damping: 20 },
  wobble: { type: 'spring', stiffness: 180, damping: 12 },
};
```

#### Stagger Patterns

| Token | Delay | Usage |
|-------|-------|-------|
| `stagger-fast` | 30ms | Dense lists, table rows |
| `stagger-normal` | 60ms | Cards, menu items |
| `stagger-slow` | 100ms | Feature reveals, dashboards |
| `stagger-cascade` | 80ms | Nested groups, trees |

---

## 4. Theme System

### 4.1 Built-in Themes

8 curated application themes, each with light and dark variants:

1. **default** — Violet-based modern (purple tint)
2. **graphite** — Cool blue-gray technical aesthetic
3. **ocean** — Teal/blue maritime feel
4. **amber** — Warm earthy tones
5. **github** — GitHub-inspired blue-gray
6. **nord** — Arctic-inspired muted palette
7. **everforest** — Natural green/brown
8. **rosepine** — Soft rose/lavender

### 4.2 Theme Implementation

```typescript
// types/theme.ts
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

// utils/theme.ts
export function applyTheme(theme: ApplicationTheme): void {
  if (theme === 'default') {
    document.documentElement.removeAttribute('data-app-theme');
  } else {
    document.documentElement.setAttribute('data-app-theme', theme);
  }
}

export function applyDarkMode(isDark: boolean): void {
  document.documentElement.classList.toggle('dark', isDark);
}
```

### 4.3 Custom Accent Color

Users can override the primary accent color. The system dynamically computes:
- The primary color
- A contrasting foreground using WCAG relative luminance
- A semi-transparent ring color

```typescript
// utils/accent.ts
const DEFAULT_ACCENT = 'oklch(0.541 0.281 293.009)';

export function applyAccentColor(color: string): void {
  const resolved = color === 'default' ? DEFAULT_ACCENT : color;
  
  document.documentElement.style.setProperty('--primary', resolved);
  document.documentElement.style.setProperty('--primary-foreground', getContrastingForeground(resolved));
  
  const ringColor = `color-mix(in srgb, ${resolved} 50%, transparent)`;
  document.documentElement.style.setProperty('--ring', ringColor);
  document.documentElement.style.setProperty('--sidebar-ring', ringColor);
}

function getContrastingForeground(color: string): string {
  const brightness = getColorBrightness(color);
  return brightness < 0.55 ? 'oklch(0.98 0 0)' : 'oklch(0.09 0 0)';
}
```

### 4.4 OLED Dark Mode

Special OLED mode for AMOLED screens:
- Pure black background (`oklch(0 0 0)`)
- Reduced glass opacity
- Adjusted shadows for pure black

Activated by adding `.oled` class to `<html>` in dark mode.

### 4.5 Theme Preview Data

Each theme has preview colors for the theme selector UI:

```typescript
export interface ThemePreview {
  light: { background: string; sidebar: string; card: string; border: string; foreground: string; primary: string };
  dark: { background: string; sidebar: string; card: string; border: string; foreground: string; primary: string };
}

export const THEME_PREVIEWS: Record<ApplicationTheme, ThemePreview> = {
  default: {
    light: { background: '#fafafa', sidebar: '#f3f4f6', card: '#ffffff', border: '#d4d4d8', foreground: '#18181b', primary: '#8b5cf6' },
    dark: { background: '#24262b', sidebar: '#1c1f24', card: '#31343a', border: '#4a4f58', foreground: '#f5f7fa', primary: '#a855f7' }
  },
  // ... etc
};
```

---

## 5. Component Architecture

### 5.1 Component Categories

```
components/
├── ui/              # Primitive shadcn/ui components
│   ├── button.tsx
│   ├── card.tsx
│   ├── input.tsx
│   ├── dialog.tsx
│   ├── dropdown-menu.tsx
│   └── ...
├── actions/         # Semantic action buttons
│   ├── action-button.tsx
│   └── action-config.ts
├── data/            # Data display components
│   ├── data-table/
│   ├── stat-card.tsx
│   ├── metric-sparkline.tsx
│   └── status-badge.tsx
├── layout/          # Layout components
│   ├── sidebar/
│   ├── app-shell.tsx
│   ├── page-header.tsx
│   └── floating-header.tsx
├── feedback/        # User feedback
│   ├── toast/
│   ├── alert.tsx
│   └── skeleton.tsx
└── charts/          # Chart wrappers
    ├── area-chart.tsx
    ├── bar-chart.tsx
    ├── gauge-chart.tsx
    └── resource-timeline.tsx
```

### 5.2 Primitive Components (shadcn/ui style)

#### Button

```typescript
// components/ui/button.tsx
import { cva, type VariantProps } from 'class-variance-authority';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 rounded-lg text-sm font-medium whitespace-nowrap ' +
  'transition-all duration-200 active:scale-[0.98] ' +
  'disabled:pointer-events-none disabled:opacity-50 ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-primary/90',
        secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
        ghost: 'hover:bg-accent hover:text-accent-foreground',
        outline: 'border border-input bg-background hover:bg-accent hover:text-accent-foreground',
        destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
      },
      size: {
        default: 'h-9 px-4 py-2',
        sm: 'h-8 rounded-md px-3',
        lg: 'h-10 rounded-md px-5',
        icon: 'h-9 w-9',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  }
);
```

**Animations:**
- **Hover**: Scale 1.02, y -1px, shadow intensifies (spring, 200ms)
- **Tap**: Scale 0.95 (instant)
- **Focus**: Ring expands from center (scale 0 → 1, 150ms)
- **Loading**: Icon spins, text fades to 0.7, width holds steady
- **Success**: Icon morphs to checkmark with bounce, background flashes green briefly
- **Ripple**: Material-style ripple on click (CSS radial-gradient)

#### Card

```typescript
// components/ui/card.tsx
interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'subtle' | 'outlined' | 'bubble';
  interactive?: boolean;
}

// Variants:
// - default: Standard card with border and shadow
// - subtle: No border, lighter background
// - outlined: Border only, minimal background
// - bubble: Full glassmorphism with radial gradients
```

**Animations:**
- **Entrance**: Scale 0.96 → 1, opacity 0 → 1, y 15 → 0 (spring, 400ms)
- **Hover**: y -4px, shadow expands, border glows primary/20 (spring, 200ms)
- **Selection**: Scale pulse 1 → 1.02 → 1, border color transitions to primary
- **Loading**: Shimmer effect sweeps diagonally across surface
- **Error**: Shake animation (x: [-8, 8, -8, 8, 0], 400ms)

**Card with Bubble Effect:**
```css
.card-bubble {
  background:
    radial-gradient(
      120% 100% at 10% 0%,
      color-mix(in oklch, var(--glass-tint) 10%, transparent) 0%,
      transparent 60%
    ),
    radial-gradient(
      120% 100% at 100% 0%,
      color-mix(in oklch, var(--glass-base) 12%, transparent) 0%,
      transparent 60%
    );
  background-color: color-mix(in oklch, var(--glass-base) 92%, transparent);
  border-radius: var(--radius-xl);
  box-shadow:
    0 8px 24px -8px color-mix(in oklch, var(--glass-shadow-color) 70%, transparent),
    0 1px 0 0 color-mix(in oklch, var(--glass-base) 30%, transparent) inset;
}
```

#### Input

```typescript
// components/ui/input.tsx
// Features:
// - bg-input/80 with backdrop-blur-sm
// - focus-visible:ring-[3px]
// - aria-invalid styling
// - File input variant
// - Selection color matching primary
```

### 5.3 Semantic Action System

Instead of generic buttons, define actions by what they do:

```typescript
// components/actions/action-config.ts
export interface ActionConfig {
  label: string;
  icon: LucideIcon;
  variant: ActionVariant;
  tone: ActionTone;
  loadingLabel?: string;
}

export const ACTION_CONFIGS = {
  start: { 
    label: 'Start', 
    icon: PlayIcon, 
    variant: 'outline', 
    tone: 'success',
    loadingLabel: 'Starting...'
  },
  stop: { 
    label: 'Stop', 
    icon: SquareIcon, 
    variant: 'outline', 
    tone: 'warning',
    loadingLabel: 'Stopping...'
  },
  restart: { 
    label: 'Restart', 
    icon: RotateCcwIcon, 
    variant: 'outline', 
    tone: 'primary',
    loadingLabel: 'Restarting...'
  },
  delete: { 
    label: 'Delete', 
    icon: TrashIcon, 
    variant: 'outline', 
    tone: 'destructive',
    loadingLabel: 'Deleting...'
  },
  deploy: { 
    label: 'Deploy', 
    icon: RocketIcon, 
    variant: 'outline', 
    tone: 'primary',
    loadingLabel: 'Deploying...'
  },
  view: { 
    label: 'View', 
    icon: EyeIcon, 
    variant: 'ghost', 
    tone: 'default'
  },
  logs: { 
    label: 'Logs', 
    icon: FileTextIcon, 
    variant: 'ghost', 
    tone: 'default'
  },
} as const;

export type ActionType = keyof typeof ACTION_CONFIGS;
```

**ActionButton Component:**
```tsx
// components/actions/action-button.tsx
interface ActionButtonProps {
  action: ActionType;
  onClick: () => void;
  loading?: boolean;
  disabled?: boolean;
  size?: 'sm' | 'default' | 'lg';
}
```

### 5.4 Status Badge System

```typescript
// components/data/status-badge.tsx
interface StatusBadgeProps {
  status: 'running' | 'stopped' | 'pending' | 'error' | 'warning' | 'info';
  label?: string;
  pulse?: boolean; // Animated pulse for running/pending
}

// Usage:
// <StatusBadge status="running" pulse />
// <StatusBadge status="error" label="Failed to start" />
```

**Status Badge Styles:**
| Status | Background | Text | Icon | Pulse |
|--------|-----------|------|------|-------|
| running | `bg-emerald-500/10` | `text-emerald-400` | Circle check | Yes |
| stopped | `bg-gray-500/10` | `text-gray-400` | Square | No |
| pending | `bg-blue-500/10` | `text-blue-400` | Loader | Yes |
| error | `bg-red-500/10` | `text-red-400` | Alert circle | No |
| warning | `bg-amber-500/10` | `text-amber-400` | Alert triangle | No |

### 5.5 Stat Card

```typescript
// components/data/stat-card.tsx
interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: LucideIcon;
  iconColor?: string;
  bgColor?: string;
  variant?: 'default' | 'mini' | 'compact';
  trend?: { value: number; direction: 'up' | 'down' }; // Percentage change
  sparkline?: number[]; // Optional mini chart
}
```

**Variants:**
- **default**: Large card with icon, value, subtitle, hover lift effect
- **mini**: Compact inline stat for header bars
- **compact**: Medium size for grid layouts

**Animations:**
- **Entrance**: Scale 0.95 → 1, opacity 0 → 1, y 20 → 0 (spring, 300ms)
- **Value update**: CountUp animation with 2s duration, easeOutCubic
- **Icon**: Subtle pulse on data refresh
- **Trend arrow**: Slide in from below with spring when value changes
- **Hover**: y -4px, shadow intensifies, icon container scales 1.1
- **Sparkline**: Path draws in from left (1s, easeOut)

### 5.6 Data Table

```typescript
// components/data/data-table/
// Built on TanStack Table v8 with:
// - Server-side pagination, sorting, filtering
// - Row selection with bulk actions
// - Column visibility persistence (localStorage)
// - Grouping with collapsible sections
// - Expandable rows for details
// - Mobile: card-based view instead of table
// - Custom view options and toolbar actions

interface DataTableProps<TData> {
  columns: ColumnDef<TData>[];
  data: TData[];
  pagination?: PaginationState;
  sorting?: SortingState;
  rowSelection?: RowSelectionState;
  onRowSelectionChange?: (selection: RowSelectionState) => void;
  meta?: {
    totalCount: number;
    pageCount: number;
  };
}
```

**Table Features:**
- Sticky header with backdrop blur
- Zebra striping (subtle)
- Hover row highlight
- Sort indicators (chevron icons)
- Empty state with illustration
- Loading skeleton state

---

## 6. Layout System

### 6.1 App Shell

```
┌─────────────────────────────────────────────────────┐
│  Sidebar  │  ┌─────────────────────────────────┐   │
│  (fixed)  │  │  Header (floating on scroll)    │   │
│           │  ├─────────────────────────────────┤   │
│           │  │                                 │   │
│           │  │         Main Content            │   │
│           │  │                                 │   │
│           │  │                                 │   │
│           │  └─────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 6.2 Sidebar

**Features:**
- Collapsible (hover to expand on desktop)
- Persistent pin state
- Grouped navigation items:
  - **Platform**: Dashboard, Servers, Environments
  - **Resources**: Images, Networks, Volumes
  - **Administration**: Users, Settings, Audit Logs
- Environment switcher (if multi-environment)
- User profile section at bottom
- Keyboard shortcuts (e.g., `g` then `d` for Dashboard)

**Mobile:**
- Hidden by default
- Slide-in drawer from left
- Overlay backdrop

```typescript
// components/layout/sidebar/
interface SidebarProps {
  isOpen: boolean;
  onToggle: () => void;
  pinned: boolean;
  onPinChange: (pinned: boolean) => void;
}

interface NavItem {
  label: string;
  icon: LucideIcon;
  href: string;
  shortcut?: string; // e.g., 'gd' for 'g' then 'd'
  badge?: number;
  children?: NavItem[];
}
```

### 6.3 Page Header

```typescript
// components/layout/page-header.tsx
interface PageHeaderProps {
  title: string;
  subtitle?: string;
  icon?: LucideIcon;
  statCards?: StatCardProps[];
  actions?: ActionButtonProps[];
  breadcrumbs?: { label: string; href?: string }[];
}
```

**Features:**
- Icon + title + subtitle
- Floating stat cards in center (desktop only)
- Action button group on right
- Breadcrumbs (optional)
- On scroll: transforms into compact floating header with backdrop blur

### 6.4 Floating Header (Scroll-Aware)

When scrolling down past the header height:
- A compact floating header appears at top
- Contains: page title, key stats, primary actions
- Backdrop blur + translucent background
- Smooth slide-in animation

```typescript
// components/layout/floating-header.tsx
// Uses IntersectionObserver to detect scroll past main header
// Appears with translateY animation
// Disappears when scrolling back to top
```

### 6.5 Resource Page Layout

Standard layout for entity management pages (Servers, Images, etc.):

```typescript
// components/layout/resource-page-layout.tsx
interface ResourcePageLayoutProps {
  title: string;
  subtitle?: string;
  icon?: LucideIcon;
  stats?: StatCardProps[];
  actions?: ActionButtonProps[];
  children: React.ReactNode;
  filters?: React.ReactNode; // Filter bar
}
```

**Structure:**
1. Page header with stats and actions
2. Filter bar (search, filters, view toggle)
3. Data table or grid
4. Pagination

---

## 7. Data Visualization

### 7.1 Chart Types

#### Area Chart (Resource Usage Over Time)
```typescript
// components/charts/area-chart.tsx
interface AreaChartProps {
  data: { timestamp: string; value: number }[];
  color?: string;
  gradient?: boolean;
  height?: number;
  showAxis?: boolean;
  showGrid?: boolean;
}
```

Usage: CPU usage, memory usage, network I/O over time

#### Bar Chart (Comparisons)
```typescript
// components/charts/bar-chart.tsx
interface BarChartProps {
  data: { label: string; value: number; color?: string }[];
  horizontal?: boolean;
  height?: number;
}
```

Usage: Server resource comparison, credit usage by user

#### Gauge Chart (Utilization)
```typescript
// components/charts/gauge-chart.tsx
interface GaugeChartProps {
  value: number; // 0-100
  max: number;
  label: string;
  warningAt?: number;
  criticalAt?: number;
}
```

Usage: CPU utilization, memory pressure, disk usage

#### Resource Timeline
```typescript
// components/charts/resource-timeline.tsx
interface ResourceTimelineProps {
  resources: {
    name: string;
    events: { start: Date; end: Date; status: string }[];
  }[];
}
```

Usage: Container lifecycle visualization, scheduled jobs

### 7.2 Chart Styling

```typescript
// Default chart configuration
const chartConfig = {
  // Colors use theme tokens
  colors: [
    'var(--chart-1)',
    'var(--chart-2)',
    'var(--chart-3)',
    'var(--chart-4)',
    'var(--chart-5)',
  ],
  // Grid lines
  grid: {
    stroke: 'var(--border)',
    strokeOpacity: 0.3,
  },
  // Axis
  axis: {
    stroke: 'var(--muted-foreground)',
    tick: { fill: 'var(--muted-foreground)' },
  },
  // Tooltip
  tooltip: {
    background: 'var(--popover)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)',
    color: 'var(--popover-foreground)',
  },
};
```

### 7.3 Sparklines

Inline mini charts for table cells and stat cards:

```typescript
// components/data/metric-sparkline.tsx
interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
  fill?: boolean;
}
```

Usage: CPU column in server table, memory trend in stat card

### 7.4 Real-Time Updates

Charts update via TanStack Query's `refetchInterval` or WebSocket subscriptions:

```typescript
// hooks/use-metrics.ts
export function useServerMetrics(serverId: string) {
  return useQuery({
    queryKey: ['servers', serverId, 'metrics'],
    queryFn: () => fetchServerMetrics(serverId),
    refetchInterval: 5000, // Poll every 5 seconds
    staleTime: 4000,
  });
}
```

---

## 8. Animation & Motion

### 8.1 Philosophy

**NukeLab is a cinematic experience.** Every interaction should feel responsive, alive, and delightful. Animations are not decoration — they are communication. They guide the eye, confirm actions, reveal hierarchy, and make the interface feel intelligent.

**Principles:**
- **Purposeful**: Every animation guides attention or provides feedback
- **Physical**: Motion follows real-world physics (springs, inertia, damping)
- **Fast**: 150-300ms for interactions, 500ms for entrances
- **Layered**: Multiple elements animate in orchestrated sequences
- **Respectful**: `prefers-reduced-motion` support everywhere

### 8.2 Animation Libraries Strategy

| Library | Use Case | Bundle Impact |
|---------|----------|---------------|
| **Framer Motion** | Component animations, gestures, AnimatePresence, layout animations | ~40kb |
| **GSAP + ScrollTrigger** | Complex timelines, scroll-driven animations, morphing | ~35kb |
| **react-countup** | Animated number counters for stats | ~5kb |
| **canvas-confetti** | Celebration effects (deploy success, milestones) | ~15kb |

**Code splitting**: Load GSAP only on pages with complex scroll animations. Load confetti dynamically.

### 8.3 Page Transitions

**Route-Level Transitions with TanStack Router + Framer Motion:**

```typescript
// components/layout/animated-page.tsx
import { motion, AnimatePresence } from 'framer-motion';

const pageVariants = {
  initial: { opacity: 0, y: 20, scale: 0.98 },
  enter: { 
    opacity: 1, 
    y: 0, 
    scale: 1,
    transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] }
  },
  exit: { 
    opacity: 0, 
    y: -20, 
    scale: 0.98,
    transition: { duration: 0.3, ease: [0.4, 0, 1, 1] }
  }
};

export function AnimatedPage({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      variants={pageVariants}
      initial="initial"
      animate="enter"
      exit="exit"
    >
      {children}
    </motion.div>
  );
}
```

**Nested Route Transitions:**
- Parent route: Fade only (300ms)
- Child route: Slide + fade (400ms)
- Modal routes: Scale from trigger element (350ms, spring)

### 8.4 List & Grid Stagger Animations

**Dashboard Cards Entrance:**
```typescript
const containerVariants = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: {
      staggerChildren: 0.08,
      delayChildren: 0.1
    }
  }
};

const itemVariants = {
  hidden: { opacity: 0, y: 30, scale: 0.95 },
  show: { 
    opacity: 1, 
    y: 0, 
    scale: 1,
    transition: { type: 'spring', stiffness: 120, damping: 14 }
  }
};

// Usage: Cards fly in with stagger, each with spring physics
```

**Table Row Stagger:**
```typescript
const tableRowVariants = {
  hidden: { opacity: 0, x: -20 },
  show: (i: number) => ({
    opacity: 1,
    x: 0,
    transition: { delay: i * 0.03, duration: 0.3, ease: 'easeOut' }
  })
};
```

**Filter/Search Reorder:**
```typescript
// When filtering, items don't just disappear — they shrink and fade
const filterVariants = {
  visible: { opacity: 1, scale: 1, height: 'auto' },
  hidden: { opacity: 0, scale: 0.9, height: 0, margin: 0 }
};
```

### 8.5 Micro-interactions

#### Button Interactions

```typescript
// components/ui/animated-button.tsx
const buttonTap = { scale: 0.95 };
const buttonHover = { 
  scale: 1.02, 
  y: -1,
  transition: { type: 'spring', stiffness: 400, damping: 17 }
};

// Success state animation
const successVariants = {
  idle: { scale: 1 },
  success: { 
    scale: [1, 1.1, 1],
    transition: { duration: 0.4 }
  }
};
```

**Ripple Effect:**
```css
/* Material-style ripple on click */
.ripple {
  position: relative;
  overflow: hidden;
}

.ripple::after {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(circle, var(--primary) 10%, transparent 10%);
  background-repeat: no-repeat;
  background-position: 50%;
  transform: scale(10);
  opacity: 0;
  transition: transform 0.5s, opacity 0.5s;
}

.ripple:active::after {
  transform: scale(0);
  opacity: 0.2;
  transition: 0s;
}
```

#### Card Interactions

```typescript
// Hover: Lift + glow + tint
const cardHover = {
  y: -4,
  boxShadow: '0 20px 40px -12px rgba(0,0,0,0.3)',
  transition: { type: 'spring', stiffness: 300, damping: 20 }
};

// Selection: Scale pulse
const cardSelect = {
  scale: [1, 1.02, 1],
  borderColor: 'var(--primary)',
  transition: { duration: 0.3 }
};
```

#### Toggle/Switch Animations

```typescript
// Smooth spring toggle
const switchVariants = {
  off: { x: 2 },
  on: { x: 22 }
};

// With background color morph
const switchBgVariants = {
  off: { backgroundColor: 'var(--muted)' },
  on: { backgroundColor: 'var(--primary)' }
};
```

### 8.6 Stat Card Animations

**Number Count-Up:**
```typescript
import CountUp from 'react-countup';

// Numbers count up from 0 on mount
<CountUp 
  end={value} 
  duration={2} 
  separator="," 
  decimals={value % 1 !== 0 ? 2 : 0}
  easingFn={(t, b, c, d) => c * (1 - Math.pow(1 - t / d, 3)) + b} // Ease out cubic
/>

// On data refresh, numbers "roll" to new value
// Use key prop to trigger re-animation: key={`${value}-${timestamp}`}
```

**Trend Indicator:**
```typescript
// Arrow slides in from below when trend changes
const trendVariants = {
  hidden: { opacity: 0, y: 10 },
  visible: { opacity: 1, y: 0, transition: { type: 'spring' } }
};

// Color morphs from neutral to green/red
```

**Icon Animations:**
```typescript
// Icon rotates or pulses on update
const iconPulse = {
  scale: [1, 1.2, 1],
  rotate: [0, 10, -10, 0],
  transition: { duration: 0.5 }
};

// On error, icon shakes
const iconShake = {
  x: [0, -5, 5, -5, 5, 0],
  transition: { duration: 0.4 }
};
```

### 8.7 Data Visualization Animations

**Chart Entrance:**
```typescript
// Charts grow from zero
const chartVariants = {
  hidden: { opacity: 0, scaleY: 0 },
  visible: { 
    opacity: 1, 
    scaleY: 1,
    transition: { duration: 0.8, ease: [0.22, 1, 0.36, 1] }
  }
};

// Bars stagger in from left
const barVariants = {
  hidden: { scaleY: 0 },
  visible: (i: number) => ({
    scaleY: 1,
    transition: { delay: i * 0.05, duration: 0.5, ease: 'easeOut' }
  })
};
```

**Real-Time Data Updates:**
```typescript
// When new data point arrives:
// 1. New point fades in at right
// 2. Line smoothly morphs to new path
// 3. Old points shift left with spring physics
// 4. Y-axis rescales with smooth transition

// Recharts + Framer Motion integration
// Use `isAnimationActive={true}` with custom duration
```

**Gauge/Progress Animations:**
```typescript
// Circular progress with spring
const progressVariants = {
  hidden: { pathLength: 0 },
  visible: { 
    pathLength: value / 100,
    transition: { type: 'spring', stiffness: 60, damping: 15 }
  }
};

// Color interpolation based on value
// 0-50: Blue → 50-80: Yellow → 80-100: Red
```

### 8.8 Modal, Drawer & Toast Animations

#### Modal

```typescript
const modalOverlayVariants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.2 } },
  exit: { opacity: 0, transition: { duration: 0.15 } }
};

const modalContentVariants = {
  hidden: { opacity: 0, scale: 0.9, y: 20 },
  visible: { 
    opacity: 1, 
    scale: 1, 
    y: 0,
    transition: { type: 'spring', stiffness: 300, damping: 25 }
  },
  exit: { 
    opacity: 0, 
    scale: 0.95, 
    y: 10,
    transition: { duration: 0.2 }
  }
};
```

#### Drawer (Mobile)

```typescript
const drawerVariants = {
  hidden: { x: '-100%' },
  visible: { 
    x: 0,
    transition: { type: 'spring', stiffness: 300, damping: 30 }
  },
  exit: { 
    x: '-100%',
    transition: { type: 'spring', stiffness: 300, damping: 30 }
  }
};
```

#### Toast Notifications

```typescript
const toastVariants = {
  hidden: { opacity: 0, y: -50, scale: 0.9 },
  visible: { 
    opacity: 1, 
    y: 0, 
    scale: 1,
    transition: { type: 'spring', stiffness: 400, damping: 25 }
  },
  exit: { 
    opacity: 0, 
    x: 100,
    transition: { duration: 0.3 }
  }
};

// Stack management: new toasts push existing ones down
// Exit: slide right + fade
```

**Progress Toast (for long operations):**
```typescript
// Toast with embedded progress bar
// Progress bar animates width with spring
// On complete: toast transforms to success state (checkmark morphs in)
```

### 8.9 Loading States

#### Skeleton Screens

```typescript
// Shimmer effect moving diagonally
const shimmer = {
  background: `linear-gradient(
    90deg,
    var(--muted) 25%,
    color-mix(in oklch, var(--muted) 80%, var(--background)) 50%,
    var(--muted) 75%
  )`,
  backgroundSize: '200% 100%',
  animation: 'shimmer 1.5s infinite'
};

// Staggered skeleton cards
const skeletonContainer = {
  show: { transition: { staggerChildren: 0.1 } }
};

const skeletonItem = {
  hidden: { opacity: 0.5 },
  show: { opacity: [0.5, 0.8, 0.5], transition: { duration: 1.5, repeat: Infinity } }
};
```

#### Spinner Variants

```typescript
// Orbital spinner for primary loading
// Three dots chasing each other in a circle
// Color: primary

// Pulse ring for secondary loading
// Expanding and fading rings
// Used for background operations

// Skeleton shimmer for content loading
// Used for initial page loads
```

#### Progressive Loading

```typescript
// Show skeleton → fade out → fade in real content
// Cross-fade duration: 300ms
// Content entrance: stagger children
```

### 8.10 Scroll-Triggered Animations

**GSAP ScrollTrigger for dashboard sections:**

```typescript
// components/animations/scroll-reveal.tsx
import { useGSAP } from '@gsap/react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

export function ScrollReveal({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  
  useGSAP(() => {
    gsap.from(ref.current, {
      y: 60,
      opacity: 0,
      duration: 0.8,
      ease: 'power3.out',
      scrollTrigger: {
        trigger: ref.current,
        start: 'top 85%',
        toggleActions: 'play none none none'
      }
    });
  }, { scope: ref });
  
  return <div ref={ref}>{children}</div>;
}
```

**Parallax Effects:**
```typescript
// Subtle parallax on decorative elements
// Speed: 0.2x (very subtle, not distracting)
// Used on: Background blobs, section dividers
```

### 8.11 Ambient & Background Effects

#### Floating Blobs (Dashboard Only)

```css
@keyframes blob-float-1 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(30px, -50px) scale(1.1); }
  66% { transform: translate(-20px, 20px) scale(0.9); }
}

@keyframes blob-float-2 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(-40px, 30px) scale(1.15); }
  66% { transform: translate(20px, -40px) scale(0.95); }
}

.ambient-blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.15;
  pointer-events: none;
}

.blob-1 {
  width: 400px;
  height: 400px;
  background: var(--primary);
  animation: blob-float-1 20s ease-in-out infinite;
}

.blob-2 {
  width: 300px;
  height: 300px;
  background: var(--chart-2);
  animation: blob-float-2 25s ease-in-out infinite;
}
```

#### Grid Pattern Animation

```css
/* Subtle animated grid behind cards */
.animated-grid {
  background-image: 
    linear-gradient(var(--border) 1px, transparent 1px),
    linear-gradient(90deg, var(--border) 1px, transparent 1px);
  background-size: 40px 40px;
  animation: grid-pan 60s linear infinite;
}

@keyframes grid-pan {
  0% { background-position: 0 0; }
  100% { background-position: 40px 40px; }
}
```

#### Noise Texture

```css
/* Subtle noise overlay for tactile depth */
.noise-overlay::after {
  content: '';
  position: fixed;
  inset: 0;
  z-index: 9999;
  background-image: url("data:image/svg+xml,..."); /* SVG noise */
  opacity: 0.03;
  pointer-events: none;
  mix-blend-mode: overlay;
}
```

### 8.12 Status & State Animations

#### Live Indicator Pulse

```css
@keyframes live-pulse {
  0%, 100% { 
    box-shadow: 0 0 0 0 color-mix(in oklch, var(--primary) 40%, transparent);
  }
  50% { 
    box-shadow: 0 0 0 8px color-mix(in oklch, var(--primary) 0%, transparent);
  }
}

.live-indicator {
  animation: live-pulse 2s ease-in-out infinite;
}
```

#### Container State Transitions

```typescript
// When container starts/stops:
// 1. Status badge morphs (color + icon)
// 2. Card border glows briefly
// 3. Progress bar appears with spring
// 4. On complete: confetti burst (optional)

const stateTransition = {
  pending: { 
    borderColor: 'var(--primary)',
    boxShadow: '0 0 20px color-mix(in oklch, var(--primary) 20%, transparent)',
  },
  running: { 
    borderColor: 'var(--success)',
    boxShadow: '0 0 20px color-mix(in oklch, var(--success) 20%, transparent)',
  },
  stopped: { 
    borderColor: 'var(--muted)',
    boxShadow: 'none',
  }
};
```

#### Error Shake

```typescript
const errorShake = {
  x: [0, -8, 8, -8, 8, -4, 4, 0],
  transition: { duration: 0.5 }
};

// Applied to: Form fields, cards, modals on error
```

### 8.13 Celebration Effects

**Deploy Success:**
```typescript
import confetti from 'canvas-confetti';

const deployConfetti = () => {
  confetti({
    particleCount: 100,
    spread: 70,
    origin: { y: 0.6 },
    colors: [var(--primary), var(--chart-2), var(--chart-3)]
  });
};

// Triggered on: Server start success, environment create, etc.
```

**Achievement Unlocked:**
```typescript
// Slide-in banner from top
// Trophy icon with bounce
// Text types out character by character
// Auto-dismiss after 5 seconds with slide-up exit
```

### 8.14 Gesture & Drag Animations

#### Swipe Actions (Mobile Tables)

```typescript
// Swipe left on table row reveals actions
const swipeVariants = {
  open: { x: -100 },
  closed: { x: 0 }
};

// Spring physics for natural feel
// Snap points at 0 and -100
// Velocity-based snap decision
```

#### Reorderable Lists

```typescript
// Drag to reorder with layout animations
// Items slide to make space
// Drop target highlighted with scale pulse
```

### 8.15 AnimatePresence Patterns

**Tab Content Switch:**
```typescript
// Content fades out + slides left
// New content fades in + slides from right
// Duration: 300ms, ease: easeInOut
```

**Accordion Expand:**
```typescript
// Height: 0 → auto (with spring)
// Content: opacity 0 → 1, delayed by 100ms
// Chevron: rotate 0 → 180
```

**Dropdown Menu:**
```typescript
// Scale: 0.95 → 1
// Opacity: 0 → 1
// Origin: top (for down), bottom (for up)
// Items stagger in: 20ms delay each
```

### 8.16 Performance Optimization

**Rules:**
- Animate only `transform` and `opacity` (GPU accelerated)
- Use `will-change` sparingly, remove after animation
- Batch DOM reads/writes
- Use `layoutId` for shared element transitions (Framer Motion)
- Debounce scroll events
- Use CSS animations for simple loops (ambient effects)
- Use Framer Motion for user-triggered animations
- Lazy load GSAP only on pages that need it

**Avoid:**
- Animating `width`, `height`, `top`, `left` (causes reflow)
- Blur filters during scroll
- Heavy particle systems without FPS limiting
- Multiple simultaneous complex animations

### 8.17 Animation Accessibility

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
  
  /* Keep essential motion: */
  /* - Instant feedback (button press) */
  /* - Critical state changes (error shake) */
  /* But make them instant, not animated */
}
```

**Reduced Motion Strategy:**
- Replace spring animations with instant state changes
- Remove ambient background animations
- Keep opacity transitions but make them instant
- Maintain color transitions for state changes
- Remove parallax effects
- Simplify page transitions to instant swaps

---

## 9. Accessibility

### 9.1 Requirements

- **WCAG 2.1 AA** compliance minimum
- All interactive elements keyboard accessible
- Focus indicators visible and consistent
- Screen reader friendly tables and charts
- Color not the only means of conveying information

### 9.2 Implementation

```typescript
// Focus management
// - useFocusTrap for modals
// - useScrollLock for drawers
// - useHotkeys for keyboard shortcuts

// ARIA
// - Proper heading hierarchy (h1 → h2 → h3)
// - aria-label for icon-only buttons
// - aria-describedby for form errors
// - role="status" for live regions
// - aria-live="polite" for toast notifications

// Color contrast
// - All text meets 4.5:1 ratio
// - Large text (18px+) meets 3:1 ratio
// - Status badges have icons + color
```

### 9.3 Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `?` | Show keyboard shortcuts help |
| `g` then `d` | Go to Dashboard |
| `g` then `s` | Go to Servers |
| `g` then `e` | Go to Environments |
| `n` then `s` | New Server |
| `/` | Focus search |
| `Esc` | Close modal/drawer |

### 9.4 Reduced Motion

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## 10. Responsive Design

### 10.1 Breakpoints

| Name | Width | Usage |
|------|-------|-------|
| `sm` | 640px | Large phones |
| `md` | 768px | Tablets |
| `lg` | 1024px | Small laptops |
| `xl` | 1280px | Desktops |
| `2xl` | 1536px | Large screens |

### 10.2 Mobile Adaptations

- **Sidebar**: Hidden, slide-in drawer
- **Tables**: Card-based list view
- **Stat cards**: Stack vertically
- **Actions**: Dropdown menu instead of button group
- **Charts**: Simplified (remove grid, smaller)
- **Modals**: Full-screen sheets
- **Page header**: Compact, no floating stats

### 10.3 Touch Targets

- Minimum 44x44px for interactive elements
- Increased padding on mobile buttons
- Swipe gestures for table rows (reveal actions)

---

## 11. File Structure

```
frontend/
├── public/
│   ├── fonts/
│   │   ├── GeistVariable.woff2
│   │   └── GeistMonoVariable.woff2
│   └── favicon.svg
├── src/
│   ├── main.tsx                 # Entry point
│   ├── route-tree.gen.ts        # Generated by TanStack Router
│   ├── routes/                  # File-based routing
│   │   ├── __root.tsx           # Root layout
│   │   ├── index.tsx            # Dashboard (landing)
│   │   ├── login.tsx            # Auth page
│   │   ├── servers/
│   │   │   ├── index.tsx        # Server list
│   │   │   └── $serverId/
│   │   │       ├── index.tsx    # Server detail
│   │   │       └── metrics.tsx  # Server metrics
│   │   ├── environments/
│   │   ├── users/
│   │   └── settings/
│   ├── components/
│   │   ├── ui/                  # shadcn primitives
│   │   ├── actions/
│   │   ├── data/
│   │   ├── layout/
│   │   ├── feedback/
│   │   └── charts/
│   ├── hooks/
│   │   ├── use-theme.ts
│   │   ├── use-media-query.ts
│   │   ├── use-keyboard-shortcuts.ts
│   │   └── use-scroll-position.ts
│   ├── lib/
│   │   ├── utils.ts             # cn(), formatters
│   │   ├── api.ts               # API client
│   │   └── websocket.ts         # WebSocket manager
│   ├── stores/
│   │   ├── theme-store.ts       # Zustand theme state
│   │   └── sidebar-store.ts     # Zustand sidebar state
│   ├── types/
│   │   ├── theme.ts
│   │   ├── api.ts
│   │   └── index.ts
│   └── styles/
│       ├── index.css            # Global styles, fonts
│       ├── themes.css           # Theme definitions
│       └── utilities.css        # Custom utilities
├── index.html
├── vite.config.ts
├── tailwind.config.ts
├── tsconfig.json
└── package.json
```

---

## 12. Implementation Roadmap

### Phase 1: Foundation (Week 1)
- [x] Set up Vite + React 19 + TanStack Router + TanStack Query
- [x] Configure Tailwind CSS v4 with OKLCH tokens
- [x] Add Geist fonts
- [x] Implement theme system (8 themes + custom accent + OLED)
- [x] Create base layout (sidebar + app shell)
- [x] Set up Zustand stores for theme and sidebar
- [x] Install animation libraries (Framer Motion, GSAP, react-countup)
- [x] Create animation token system (durations, easings, springs)
- [x] Set up AnimatePresence wrapper for route transitions

### Phase 2: Design System (Week 2)
- [x] Build primitive components (Button, Card, Input, Dialog) with animations
- [x] Implement glassmorphism utilities (bubble, bubble-outline)
- [x] Create semantic action button system with ripple + state animations
- [x] Build status badge component with pulse + state transitions
- [x] Create stat card component with CountUp + sparkline animations
- [x] Implement custom scrollbars
- [x] Build reusable animation wrappers (FadeIn, SlideUp, ScaleIn, StaggerContainer)
- [x] Create loading skeletons with shimmer effect

### Phase 3: Data Components (Week 3)
- [x] Build data table with TanStack Table
- [x] Add server-side pagination, sorting, filtering
- [x] Implement row selection and bulk actions
- [x] Create mobile card view for tables
- [x] Build page header with floating header behavior
- [x] Create resource page layout

### Phase 4: Visualization (Week 4)
- [ ] Set up Recharts with theme integration
- [ ] Build area chart component
- [ ] Build bar chart component
- [ ] Build gauge chart component
- [ ] Create sparkline component
- [ ] Implement real-time metrics dashboard

### Phase 5: Animation & Polish (Week 5)
- [ ] Implement page transition animations
- [ ] Add list/grid stagger animations
- [ ] Create toast notification system with spring animations
- [ ] Add modal/drawer entrance/exit animations
- [ ] Implement scroll-triggered animations (GSAP ScrollTrigger)
- [ ] Add ambient background effects (floating blobs, grid pattern)
- [ ] Create celebration effects (confetti on deploy success)
- [ ] Implement drag/swipe gesture animations
- [ ] Add keyboard shortcuts
- [ ] Create empty states with illustrations
- [ ] Add error boundaries with friendly error animations
- [ ] Implement reduced motion support
- [ ] Mobile responsiveness pass
- [ ] Accessibility audit
- [ ] Performance audit (animation frame rates, bundle size)

### Phase 6: Migration (Week 6)
- [ ] Migrate existing pages to new design system
- [ ] Wire up API endpoints with TanStack Query
- [ ] Implement WebSocket integration for real-time data
- [ ] Performance optimization (code splitting, lazy loading)
- [x] Remove old Next.js frontend
- [ ] Update deployment scripts for static files

---

## Appendix A: Tailwind Configuration

```typescript
// tailwind.config.ts
import type { Config } from 'tailwindcss';

const config: Config = {
  darkMode: ['class'],
  content: ['./src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Geist', 'system-ui', 'sans-serif'],
        mono: ['Geist Mono', 'monospace'],
      },
      colors: {
        background: 'var(--background)',
        foreground: 'var(--foreground)',
        card: { DEFAULT: 'var(--card)', foreground: 'var(--card-foreground)' },
        popover: { DEFAULT: 'var(--popover)', foreground: 'var(--popover-foreground)' },
        primary: { DEFAULT: 'var(--primary)', foreground: 'var(--primary-foreground)' },
        secondary: { DEFAULT: 'var(--secondary)', foreground: 'var(--secondary-foreground)' },
        muted: { DEFAULT: 'var(--muted)', foreground: 'var(--muted-foreground)' },
        accent: { DEFAULT: 'var(--accent)', foreground: 'var(--accent-foreground)' },
        destructive: { DEFAULT: 'var(--destructive)', foreground: 'var(--destructive-foreground)' },
        border: 'var(--border)',
        input: 'var(--input)',
        ring: 'var(--ring)',
        surface: 'var(--surface)',
        sidebar: {
          DEFAULT: 'var(--sidebar)',
          foreground: 'var(--sidebar-foreground)',
          primary: 'var(--sidebar-primary)',
          'primary-foreground': 'var(--sidebar-primary-foreground)',
          accent: 'var(--sidebar-accent)',
          'accent-foreground': 'var(--sidebar-accent-foreground)',
          border: 'var(--sidebar-border)',
          ring: 'var(--sidebar-ring)',
        },
      },
      borderRadius: {
        sm: 'calc(var(--radius) - 4px)',
        md: 'calc(var(--radius) - 2px)',
        lg: 'var(--radius)',
        xl: 'calc(var(--radius) + 4px)',
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
};

export default config;
```

## Appendix B: CSS Reset & Base

```css
/* src/styles/index.css */
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  * {
    @apply border-border;
  }

  html {
    scroll-behavior: smooth;
  }

  body {
    @apply bg-background text-foreground antialiased;
    font-feature-settings: 'rlig' 1, 'calt' 1;
  }

  /* Custom scrollbar */
  * {
    scrollbar-width: thin;
    scrollbar-color: transparent transparent;
  }

  *:hover {
    scrollbar-color: var(--muted-foreground) transparent;
  }

  *::-webkit-scrollbar {
    width: 8px;
    height: 8px;
  }

  *::-webkit-scrollbar-track {
    background: transparent;
    border-radius: 4px;
  }

  *::-webkit-scrollbar-thumb {
    background: transparent;
    border-radius: 4px;
    border: 2px solid transparent;
    background-clip: content-box;
    transition: background 0.2s ease;
  }

  *:hover::-webkit-scrollbar-thumb {
    background: var(--muted-foreground);
  }

  *::-webkit-scrollbar-thumb:hover {
    background: var(--foreground) !important;
  }

  /* Autofill override */
  input:-webkit-autofill,
  input:-webkit-autofill:hover,
  input:-webkit-autofill:focus {
    -webkit-box-shadow: 0 0 0 9999px transparent inset !important;
    -webkit-text-fill-color: var(--foreground) !important;
    transition: background-color 5000s ease-in-out 0s;
  }

  /* Selection */
  ::selection {
    background: color-mix(in oklch, var(--primary) 30%, transparent);
    color: var(--foreground);
  }
}

@layer utilities {
  .bubble {
    background:
      radial-gradient(
        120% 100% at 10% 0%,
        color-mix(in oklch, var(--glass-tint, var(--primary)) 10%, transparent) 0%,
        transparent 60%
      ),
      radial-gradient(
        120% 100% at 100% 0%,
        color-mix(in oklch, var(--glass-base, var(--bg-surface)) 12%, transparent) 0%,
        transparent 60%
      );
    background-color: color-mix(in oklch, var(--glass-base, var(--bg-surface)) 92%, transparent);
    border-radius: var(--radius-xl);
    box-shadow:
      0 8px 24px -8px color-mix(in oklch, var(--glass-shadow-color) 70%, transparent),
      0 1px 0 0 color-mix(in oklch, var(--glass-base, var(--bg-surface)) 30%, transparent) inset;
  }

  .bubble-outline {
    background:
      linear-gradient(var(--glass-base, var(--bg-surface)), var(--glass-base, var(--bg-surface))) padding-box,
      linear-gradient(135deg, color-mix(in oklch, var(--glass-tint, var(--primary)) 28%, transparent), transparent 60%) border-box;
    border: 1px solid transparent;
    border-radius: var(--radius-lg);
  }

  .hover-lift {
    transition: transform 200ms ease, box-shadow 200ms ease;
  }

  .hover-lift:hover {
    transform: translateY(-2px) translateZ(0);
  }

  /* Shimmer loading effect */
  .shimmer {
    background: linear-gradient(
      90deg,
      var(--muted) 25%,
      color-mix(in oklch, var(--muted) 70%, var(--background)) 50%,
      var(--muted) 75%
    );
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
  }

  /* Live pulse indicator */
  .live-pulse {
    animation: live-pulse 2s ease-in-out infinite;
  }

  /* Floating ambient blob */
  .blob-float {
    animation: blob-float-1 20s ease-in-out infinite;
  }

  /* Grid pattern pan */
  .grid-pan {
    animation: grid-pan 60s linear infinite;
  }
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

@keyframes live-pulse {
  0%, 100% { 
    box-shadow: 0 0 0 0 color-mix(in oklch, var(--primary) 40%, transparent);
  }
  50% { 
    box-shadow: 0 0 0 8px color-mix(in oklch, var(--primary) 0%, transparent);
  }
}

@keyframes blob-float-1 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(30px, -50px) scale(1.1); }
  66% { transform: translate(-20px, 20px) scale(0.9); }
}

@keyframes blob-float-2 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(-40px, 30px) scale(1.15); }
  66% { transform: translate(20px, -40px) scale(0.95); }
}

@keyframes grid-pan {
  0% { background-position: 0 0; }
  100% { background-position: 40px 40px; }
}

@keyframes shake {
  0%, 100% { transform: translateX(0); }
  10%, 30%, 50%, 70%, 90% { transform: translateX(-4px); }
  20%, 40%, 60%, 80% { transform: translateX(4px); }
}
```

## Appendix C: API Integration Pattern

```typescript
// lib/api.ts
import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 30, // 30 seconds
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});

// API client with interceptors for auth
const api = {
  async get<T>(path: string): Promise<T> {
    const response = await fetch(`/api${path}`, {
      headers: {
        'Authorization': `Bearer ${getToken()}`,
        'Content-Type': 'application/json',
      },
    });
    if (!response.ok) throw new Error(await response.text());
    return response.json();
  },
  // ... post, put, delete
};

// Query hooks
export function useServers() {
  return useQuery({
    queryKey: ['servers'],
    queryFn: () => api.get<Server[]>('/servers'),
  });
}

export function useServerMetrics(serverId: string) {
  return useQuery({
    queryKey: ['servers', serverId, 'metrics'],
    queryFn: () => api.get<Metrics>(`/servers/${serverId}/metrics`),
    refetchInterval: 5000,
  });
}
```

## Appendix D: Reusable Animation Components

```typescript
// components/animations/

// FadeIn — Simple opacity fade
export function FadeIn({ children, delay = 0, duration = 0.5 }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration, delay }}
    >
      {children}
    </motion.div>
  );
}

// SlideUp — Entrance from below
export function SlideUp({ children, delay = 0, duration = 0.5, y = 30 }) {
  return (
    <motion.div
      initial={{ opacity: 0, y }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}

// ScaleIn — Pop-in effect
export function ScaleIn({ children, delay = 0 }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ type: 'spring', stiffness: 200, damping: 20, delay }}
    >
      {children}
    </motion.div>
  );
}

// StaggerContainer — Orchestrates children animations
export function StaggerContainer({ children, staggerDelay = 0.06, delayChildren = 0.1 }) {
  return (
    <motion.div
      variants={{
        hidden: { opacity: 0 },
        show: {
          opacity: 1,
          transition: { staggerChildren: staggerDelay, delayChildren }
        }
      }}
      initial="hidden"
      animate="show"
    >
      {children}
    </motion.div>
  );
}

// StaggerItem — Child of StaggerContainer
export function StaggerItem({ children }) {
  return (
    <motion.div
      variants={{
        hidden: { opacity: 0, y: 30, scale: 0.95 },
        show: { 
          opacity: 1, 
          y: 0, 
          scale: 1,
          transition: { type: 'spring', stiffness: 120, damping: 14 }
        }
      }}
    >
      {children}
    </motion.div>
  );
}

// HoverScale — Interactive scale on hover
export function HoverScale({ children, scale = 1.02 }) {
  return (
    <motion.div whileHover={{ scale }} whileTap={{ scale: 0.98 }}>
      {children}
    </motion.div>
  );
}

// AnimatedNumber — CountUp wrapper
export function AnimatedNumber({ value, duration = 2, decimals = 0 }) {
  return (
    <CountUp
      end={value}
      duration={duration}
      decimals={decimals}
      separator=","
      easingFn={(t, b, c, d) => c * (1 - Math.pow(1 - t / d, 3)) + b}
    />
  );
}

// ScrollReveal — GSAP ScrollTrigger wrapper
export function ScrollReveal({ children, y = 60, duration = 0.8 }) {
  const ref = useRef<HTMLDivElement>(null);
  
  useGSAP(() => {
    gsap.from(ref.current, {
      y,
      opacity: 0,
      duration,
      ease: 'power3.out',
      scrollTrigger: {
        trigger: ref.current,
        start: 'top 85%',
        toggleActions: 'play none none none'
      }
    });
  }, { scope: ref });
  
  return <div ref={ref}>{children}</div>;
}

// PageTransition — Route-level transition
export function PageTransition({ children }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -20, scale: 0.98 }}
      transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}

// Toast — Animated notification
export function AnimatedToast({ message, type, onDismiss }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -50, scale: 0.9 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, x: 100 }}
      transition={{ type: 'spring', stiffness: 400, damping: 25 }}
      layout
    >
      {message}
    </motion.div>
  );
}

// Skeleton — Shimmer loading state
export function Skeleton({ width, height, circle = false }) {
  return (
    <motion.div
      className="shimmer bg-muted"
      style={{ width, height, borderRadius: circle ? '50%' : '4px' }}
      initial={{ opacity: 0.5 }}
      animate={{ opacity: [0.5, 0.8, 0.5] }}
      transition={{ duration: 1.5, repeat: Infinity }}
    />
  );
}

// LiveIndicator — Pulsing status dot
export function LiveIndicator() {
  return (
    <span className="relative flex h-3 w-3">
      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
      <span className="relative inline-flex rounded-full h-3 w-3 bg-primary"></span>
    </span>
  );
}
```

---

**Document End**

*This specification is a living document. Update as implementation reveals edge cases or new requirements.*
