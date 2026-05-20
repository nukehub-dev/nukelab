import { createFileRoute, Link } from '@tanstack/react-router';
import { motion } from 'framer-motion';
import { Palette, Moon, Sun, Monitor, Check, Sidebar, ArrowLeft } from 'lucide-react';
import { useThemeStore } from '../stores/theme-store';
import { useSidebarStore } from '../stores/sidebar-store';
import { THEME_VALUES, THEME_PREVIEWS, ACCENT_COLORS } from '../types/theme';
import { cn } from '../lib/utils';
import { Tooltip } from '../components/ui/tooltip';

export const Route = createFileRoute('/settings/appearance')({
  component: AppearanceSettingsPage,
});

function AppearanceSettingsPage() {
  const {
    theme,
    isDark,
    isOled,
    accentColor,
    setTheme,
    setDarkMode,
    setOledMode,
    setAccentColor
  } = useThemeStore();

  const { mode, setMode } = useSidebarStore();

  return (
    <div className="min-h-screen p-6 lg:p-10 space-y-10">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center gap-3"
      >
        <Link
          to="/settings"
          className="p-2 rounded-lg hover:bg-accent transition-colors shrink-0 inline-flex"
        >
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="p-2 rounded-xl bg-primary/10">
          <Palette className="w-5 h-5 text-primary" />
        </div>
        <div>
          <h1 className="text-xl font-bold">Appearance</h1>
          <p className="text-sm text-muted-foreground">Customize the look and feel of NukeLab</p>
        </div>
      </motion.div>

      <div className="space-y-8">
        {/* Application Theme */}
        <SettingsSection title="Application Theme" description="Choose the overall visual theme for NukeLab.">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {THEME_VALUES.map((t) => (
              <motion.button
                key={t}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                onClick={() => setTheme(t)}
                className={cn(
                  "relative p-4 rounded-xl border-2 transition-all text-left",
                  theme === t
                    ? "border-primary bg-primary/5"
                    : "border-border/50 bg-card/30 hover:border-border hover:bg-card/50"
                )}
              >
                <div className="space-y-3">
                  <div
                    className="w-full h-12 rounded-lg border border-border/20 overflow-hidden relative flex items-end p-1 gap-1"
                    style={{
                      backgroundColor: isDark ? THEME_PREVIEWS[t].dark.background : THEME_PREVIEWS[t].light.background,
                      borderColor: isDark ? THEME_PREVIEWS[t].dark.border : THEME_PREVIEWS[t].light.border,
                    }}
                  >
                    <div
                      className="h-6 rounded flex-1"
                      style={{ backgroundColor: isDark ? THEME_PREVIEWS[t].dark.card : THEME_PREVIEWS[t].light.card }}
                    />
                    <div
                      className="w-4 h-4 rounded-full shrink-0"
                      style={{ backgroundColor: isDark ? THEME_PREVIEWS[t].dark.primary : THEME_PREVIEWS[t].light.primary }}
                    />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium capitalize">{t}</span>
                    {theme === t && (
                      <div className="w-5 h-5 rounded-full bg-primary flex items-center justify-center">
                        <Check className="w-3 h-3 text-primary-foreground" />
                      </div>
                    )}
                  </div>
                </div>
              </motion.button>
            ))}
          </div>
        </SettingsSection>

        {/* Accent Color */}
        <SettingsSection title="Accent Color" description="Select an accent color to customize the appearance.">
          <div className="flex items-center gap-4">
            {ACCENT_COLORS.map((c) => (
              <Tooltip key={c.value} content={c.label}>
                <motion.button
                  whileHover={{ scale: 1.15 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={() => setAccentColor(c.value)}
                  className={cn(
                    "relative w-12 h-12 rounded-full transition-all ring-2 ring-offset-2 ring-offset-background",
                    accentColor === c.value
                      ? "ring-primary"
                      : "ring-transparent hover:ring-border"
                  )}
                  style={{ backgroundColor: c.color }}
                >
                  {accentColor === c.value && (
                    <motion.div
                      initial={{ scale: 0 }}
                      animate={{ scale: 1 }}
                      className="absolute inset-0 flex items-center justify-center"
                    >
                      <Check className="w-6 h-6 text-white drop-shadow-md" />
                    </motion.div>
                  )}
                </motion.button>
              </Tooltip>
            ))}
          </div>
        </SettingsSection>

        {/* Theme Settings - Combined card with rows */}
        <SettingsSection>
          <div className="divide-y divide-border/50">
            {/* Theme Mode */}
            <div className="flex items-center justify-between py-5 first:pt-0">
              <div className="space-y-1">
                <h3 className="text-base font-semibold">Theme Mode</h3>
                <p className="text-sm text-muted-foreground">Choose between light and dark mode</p>
              </div>
              <div className="flex items-center gap-2 p-1 bg-muted rounded-xl shrink-0">
                <button
                  onClick={() => setDarkMode(false)}
                  className={cn(
                    "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all",
                    !isDark
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  <Sun className="w-4 h-4" />
                  Light
                </button>
                <button
                  onClick={() => setDarkMode(true)}
                  className={cn(
                    "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all",
                    isDark && !isOled
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  <Moon className="w-4 h-4" />
                  Dark
                </button>
                <button
                  onClick={() => { setDarkMode(true); setOledMode(!isOled); }}
                  className={cn(
                    "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all",
                    isOled
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  <Monitor className="w-4 h-4" />
                  OLED
                </button>
              </div>
            </div>


          </div>
        </SettingsSection>

        {/* Desktop Sidebar */}
        <SettingsSection>
          <div className="divide-y divide-border/50">
            <div className="flex items-center justify-between py-5">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <Sidebar className="w-4 h-4 text-muted-foreground" />
                  <h3 className="text-base font-semibold">Sidebar Behavior</h3>
                </div>
                <p className="text-sm text-muted-foreground">Choose how the sidebar behaves</p>
              </div>
              <div className="flex items-center gap-2 p-1 bg-muted rounded-xl shrink-0">
                <button
                  onClick={() => setMode('collapsed')}
                  className={cn(
                    "px-4 py-2 rounded-lg text-sm font-medium transition-all",
                    mode === 'collapsed'
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  Collapsed
                </button>
                <button
                  onClick={() => setMode('auto')}
                  className={cn(
                    "px-4 py-2 rounded-lg text-sm font-medium transition-all",
                    mode === 'auto'
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  Auto
                </button>
                <button
                  onClick={() => setMode('expanded')}
                  className={cn(
                    "px-4 py-2 rounded-lg text-sm font-medium transition-all",
                    mode === 'expanded'
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  Expanded
                </button>
              </div>
            </div>
          </div>
        </SettingsSection>
      </div>
    </div>
  );
}

function SettingsSection({
  title,
  description,
  children
}: {
  title?: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="p-8 rounded-2xl bg-card/40 border border-border/50 backdrop-blur-sm"
    >
      {(title || description) && (
        <div className="mb-6">
          {title && <h3 className="text-lg font-semibold">{title}</h3>}
          {description && (
            <p className="text-sm text-muted-foreground mt-1">{description}</p>
          )}
        </div>
      )}
      <div>{children}</div>
    </motion.div>
  );
}
