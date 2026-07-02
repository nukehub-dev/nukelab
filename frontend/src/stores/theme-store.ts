// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { ApplicationTheme, AccentColor } from '../types/theme'
import { applyTheme, applyDarkMode, applyOledMode, applyAccentColor } from '../lib/theme'

interface ThemeState {
  theme: ApplicationTheme
  isDark: boolean
  isOled: boolean
  accentColor: AccentColor
  density: 'compact' | 'comfortable'
  setTheme: (theme: ApplicationTheme) => void
  setDarkMode: (isDark: boolean) => void
  setOledMode: (isOled: boolean) => void
  setAccentColor: (color: AccentColor) => void
  setDensity: (density: 'compact' | 'comfortable') => void
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: 'default',
      isDark: true,
      isOled: false,
      accentColor: 'default',
      density: 'comfortable',
      setTheme: (theme) => {
        set({ theme })
        applyTheme(theme)
      },
      setDarkMode: (isDark) => {
        set({ isDark })
        applyDarkMode(isDark)
      },
      setOledMode: (isOled) => {
        set({ isOled })
        applyOledMode(isOled)
      },
      setAccentColor: (color) => {
        set({ accentColor: color })
        applyAccentColor(color)
      },
      setDensity: (density) => {
        set({ density })
      },
    }),
    {
      name: 'nukelab-theme',
      onRehydrateStorage: () => (state) => {
        if (state) {
          applyTheme(state.theme)
          applyDarkMode(state.isDark)
          applyOledMode(state.isOled)
          applyAccentColor(state.accentColor)
        }
      },
    }
  )
)
