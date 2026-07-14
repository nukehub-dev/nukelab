// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import {
  Activity,
  Boxes,
  CreditCard,
  FolderOpen,
  HardDrive,
  LayoutDashboard,
  LifeBuoy,
  Loader2,
  Search,
  Server,
  Settings,
  Shield,
  UserCircle,
  X,
} from 'lucide-react'
import { useSearch } from '../../hooks/use-search'
import { cn, formatBytes } from '../../lib/utils'
import { PERMISSIONS, useAuthStore } from '../../stores/auth-store'
import type { SearchScope } from '../../types/api'
import { Modal } from '../ui/modal'

type EntityType = 'server' | 'volume' | 'workspace' | 'environment' | 'user'

interface PaletteItem {
  type: EntityType | 'page' | 'scope'
  id: string
  label: string
  subtitle?: string
  icon: React.ElementType
  /** Static page commands only; entity results route by type + id. */
  to?: string
}

interface RecentEntry {
  type: EntityType
  id: string
  label: string
  subtitle?: string
}

interface Section {
  title: string
  items: PaletteItem[]
}

const RECENTS_KEY = 'nukelab-search-recent'
const MAX_RECENTS = 5

const entityIcons: Record<EntityType, React.ElementType> = {
  server: Server,
  volume: HardDrive,
  workspace: FolderOpen,
  environment: Boxes,
  user: UserCircle,
}

const SCOPE_NAMES = ['servers', 'volumes', 'workspaces', 'environments', 'users'] as const

const scopeMeta: Record<
  SearchScope,
  { label: string; icon: React.ElementType; permission?: string }
> = {
  servers: { label: 'Servers', icon: Server },
  volumes: { label: 'Volumes', icon: HardDrive },
  workspaces: { label: 'Workspaces', icon: FolderOpen },
  environments: { label: 'Environments', icon: Boxes, permission: PERMISSIONS.ENVIRONMENT_READ },
  users: { label: 'Users', icon: UserCircle, permission: PERMISSIONS.USERS_READ },
}

function toSearchScope(token: string | undefined): SearchScope | null {
  const lower = token?.toLowerCase() ?? ''
  return (SCOPE_NAMES as readonly string[]).includes(lower) ? (lower as SearchScope) : null
}

/**
 * Detect a leading scope token, Slack/Linear-style, case-insensitive:
 * `users: john` (converts as soon as the colon is typed) or `/users john` /
 * `/users` (converts once the token is complete). Returns the scope and the
 * remaining query text with leading whitespace stripped.
 */
function parseScopePrefix(input: string): { scope: SearchScope; rest: string } | null {
  const colon = /^([a-z]+):(.*)$/i.exec(input)
  const colonScope = toSearchScope(colon?.[1])
  if (colon && colonScope) return { scope: colonScope, rest: colon[2].trimStart() }
  const slash = /^\/([a-z]+)(?:\s+(.*))?$/i.exec(input)
  const slashScope = toSearchScope(slash?.[1])
  if (slash && slashScope) return { scope: slashScope, rest: (slash[2] ?? '').trimStart() }
  return null
}

const kbdClass =
  'px-2 py-0.5 text-xs font-medium rounded bg-muted border border-border text-muted-foreground'

function loadRecents(): RecentEntry[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(RECENTS_KEY) ?? '[]')
    return Array.isArray(parsed) ? (parsed as RecentEntry[]).slice(0, MAX_RECENTS) : []
  } catch {
    return []
  }
}

function pushRecent(entry: RecentEntry) {
  const next = [
    entry,
    ...loadRecents().filter((r) => !(r.type === entry.type && r.id === entry.id)),
  ].slice(0, MAX_RECENTS)
  try {
    localStorage.setItem(RECENTS_KEY, JSON.stringify(next))
  } catch {
    // Recents are best-effort; storage may be unavailable.
  }
}

// Refocus the input after scope chip interactions (same DOM-query pattern as
// the global shortcuts' `[data-modal-close]` lookup)
function focusSearchInput() {
  document.querySelector<HTMLInputElement>('[data-search-input]')?.focus()
}

export function CommandPalette() {
  const [isOpen, setIsOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [recents, setRecents] = useState<RecentEntry[]>([])
  const [scope, setScope] = useState<SearchScope | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const hasPermission = useAuthStore((state) => state.hasPermission)
  const canAccessAdmin = useAuthStore((state) => state.canAccessAdmin)

  // Open on the global `show-search` event (same pattern as ShortcutsModal)
  useEffect(() => {
    const handleShow = () => {
      setQuery('')
      setDebouncedQuery('')
      setSelectedIndex(0)
      setRecents(loadRecents())
      setScope(null)
      setIsOpen(true)
    }
    window.addEventListener('show-search', handleShow)
    return () => window.removeEventListener('show-search', handleShow)
  }, [])

  // Debounce the search input by 300 ms
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 300)
    return () => clearTimeout(timer)
  }, [query])

  // A leading `/` with no active scope lists scopes instead of searching
  const isSlashMode = !scope && query.startsWith('/')
  const trimmed = debouncedQuery.trim()
  const canSearch = !isSlashMode && query.trim().length >= 2
  const { data, isFetching, isError } = useSearch(isSlashMode ? '' : trimmed, scope)
  // Also show the spinner while the debounce has not caught up with the input
  const searching = canSearch && (isFetching || trimmed !== query.trim())

  // Scopes the current user may filter by (mirrors the API's per-group RBAC)
  const availableScopes = useMemo(
    () =>
      SCOPE_NAMES.filter((name) => {
        const permission = scopeMeta[name].permission
        return !permission || hasPermission(permission)
      }),
    [hasPermission]
  )

  // Static "Go to" page commands, gated exactly like the sidebar nav items
  const pageCommands = useMemo<PaletteItem[]>(() => {
    const page = (label: string, to: string, icon: React.ElementType): PaletteItem => ({
      type: 'page',
      id: to,
      label,
      to,
      icon,
    })
    return [
      page('Dashboard', '/', LayoutDashboard),
      page('Servers', '/servers', Server),
      page('Usage', '/usage', Activity),
      ...(hasPermission(PERMISSIONS.ENVIRONMENT_READ)
        ? [page('Environments', '/environments', Boxes)]
        : []),
      page('Volumes', '/volumes', HardDrive),
      page('Workspaces', '/workspaces', FolderOpen),
      ...(hasPermission(PERMISSIONS.PLAN_READ) ? [page('Plans', '/plans', CreditCard)] : []),
      page('Settings', '/settings', Settings),
      ...(canAccessAdmin() ? [page('Administration', '/admin', Shield)] : []),
      page('Support', '/support', LifeBuoy),
    ]
  }, [hasPermission, canAccessAdmin])

  const sections = useMemo<Section[]>(() => {
    if (isSlashMode) {
      const filter = query.slice(1).toLowerCase()
      const items: PaletteItem[] = availableScopes
        .filter((name) => name.includes(filter))
        .map((name) => ({
          type: 'scope',
          id: name,
          label: `Search ${name}`,
          icon: scopeMeta[name].icon,
        }))
      return items.length > 0 ? [{ title: 'Scopes', items }] : []
    }
    if (!canSearch) {
      const filter = query.trim().toLowerCase()
      const result: Section[] = []
      if (recents.length > 0) {
        result.push({
          title: 'Recent',
          items: recents.map((r) => ({ ...r, icon: entityIcons[r.type] })),
        })
      }
      const commands = pageCommands.filter((c) => c.label.toLowerCase().includes(filter))
      if (commands.length > 0) result.push({ title: 'Go to', items: commands })
      return result
    }
    if (!data) return []
    const result: Section[] = []
    if (data.servers?.length) {
      result.push({
        title: 'Servers',
        items: data.servers.map((s) => ({
          type: 'server',
          id: s.id,
          label: s.name,
          subtitle: s.status,
          icon: Server,
        })),
      })
    }
    if (data.volumes?.length) {
      result.push({
        title: 'Volumes',
        items: data.volumes.map((v) => {
          const label = v.display_name || v.name
          const subtitle = [v.name !== label ? v.name : null, formatBytes(v.size_bytes), v.status]
            .filter((part): part is string => Boolean(part))
            .join(' · ')
          return { type: 'volume', id: v.id, label, subtitle, icon: HardDrive }
        }),
      })
    }
    if (data.workspaces?.length) {
      result.push({
        title: 'Workspaces',
        items: data.workspaces.map((w) => ({
          type: 'workspace',
          id: w.id,
          label: w.name,
          icon: FolderOpen,
        })),
      })
    }
    if (data.environments?.length) {
      result.push({
        title: 'Environments',
        items: data.environments.map((e) => ({
          type: 'environment',
          id: e.id,
          label: e.name,
          subtitle: e.category,
          icon: Boxes,
        })),
      })
    }
    if (data.users?.length) {
      result.push({
        title: 'Users',
        items: data.users.map((u) => ({
          type: 'user',
          id: u.id,
          label: u.username,
          subtitle: u.email ?? undefined,
          icon: UserCircle,
        })),
      })
    }
    return result
  }, [isSlashMode, canSearch, query, recents, pageCommands, availableScopes, data])

  // One flat selection index across all visible rows
  const flatItems = useMemo(() => sections.flatMap((s) => s.items), [sections])
  const activeIndex = flatItems.length === 0 ? -1 : Math.min(selectedIndex, flatItems.length - 1)

  // Keep the selected row visible while navigating with the keyboard
  useEffect(() => {
    if (activeIndex < 0) return
    listRef.current
      ?.querySelector(`[data-index="${activeIndex}"]`)
      ?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex])

  const handleOpenChange = (v: boolean) => {
    if (!v) setScope(null)
    setIsOpen(v)
  }

  const clearScope = () => {
    setScope(null)
    focusSearchInput()
  }

  // A leading scope token converts into the removable scope chip
  const handleQueryChange = (value: string) => {
    if (!scope) {
      const parsed = parseScopePrefix(value)
      if (parsed) {
        setScope(parsed.scope)
        setQuery(parsed.rest)
        setSelectedIndex(0)
        return
      }
    }
    setQuery(value)
    setSelectedIndex(0)
  }

  const openItem = (item: PaletteItem) => {
    if (item.type === 'scope') {
      setScope(item.id as SearchScope)
      setQuery('')
      setDebouncedQuery('')
      setSelectedIndex(0)
      focusSearchInput()
      return
    }
    switch (item.type) {
      case 'server':
        navigate({ to: '/servers/$serverId', params: { serverId: item.id } })
        break
      case 'workspace':
        navigate({ to: '/workspaces/$workspaceId', params: { workspaceId: item.id } })
        break
      case 'volume':
        navigate({ to: '/volumes' })
        break
      case 'environment':
        navigate({ to: '/environments' })
        break
      case 'user':
        navigate({ to: '/admin/users' })
        break
      case 'page':
        if (item.to) navigate({ to: item.to })
        break
    }
    if (item.type !== 'page') {
      pushRecent({ type: item.type, id: item.id, label: item.label, subtitle: item.subtitle })
      setRecents(loadRecents())
    }
    setQuery('')
    setDebouncedQuery('')
    setScope(null)
    setIsOpen(false)
  }

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        if (flatItems.length > 0) setSelectedIndex((i) => (i + 1) % flatItems.length)
        break
      case 'ArrowUp':
        event.preventDefault()
        if (flatItems.length > 0)
          setSelectedIndex((i) => (i - 1 + flatItems.length) % flatItems.length)
        break
      case 'Enter':
        event.preventDefault()
        if (activeIndex >= 0) openItem(flatItems[activeIndex])
        break
      case 'Escape':
        event.preventDefault()
        event.stopPropagation()
        handleOpenChange(false)
        break
      case 'Backspace':
        // Backspace in an empty input removes the active scope chip
        if (scope && query === '') {
          event.preventDefault()
          setScope(null)
        }
        break
    }
  }

  // Track the flat row index across section boundaries
  let nextIndex = 0
  const indexedSections = sections.map((section) => ({
    ...section,
    items: section.items.map((item) => ({ ...item, index: nextIndex++ })),
  }))

  const ScopeIcon = scope ? scopeMeta[scope].icon : null

  return (
    <Modal
      open={isOpen}
      onOpenChange={handleOpenChange}
      showClose={false}
      className="bubble max-w-xl"
    >
      {/* Search input */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-border/50">
        <Search className="w-5 h-5 text-muted-foreground shrink-0" />
        {scope && ScopeIcon && (
          <span className="flex items-center gap-1.5 py-1 pl-2 pr-1 rounded-md bg-accent text-accent-foreground text-xs font-medium shrink-0">
            <ScopeIcon className="w-3.5 h-3.5" />
            {scopeMeta[scope].label}
            <button
              type="button"
              onClick={clearScope}
              className="p-0.5 rounded hover:bg-background/30 transition-colors"
            >
              <X className="w-3 h-3" />
            </button>
          </span>
        )}
        <input
          data-search-input
          autoFocus
          type="text"
          value={query}
          onChange={(e) => handleQueryChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={scope ? `Search ${scope}…` : 'Search servers, volumes, workspaces…'}
          className="flex-1 min-w-0 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />
        {searching && <Loader2 className="w-4 h-4 animate-spin text-muted-foreground shrink-0" />}
      </div>

      {/* Results */}
      <div ref={listRef} className="max-h-80 overflow-y-auto px-3 py-3">
        {canSearch && isError ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Search unavailable</p>
        ) : flatItems.length === 0 ? (
          searching ? (
            <div className="flex justify-center py-6">
              <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No results for &ldquo;{query.trim()}&rdquo;
            </p>
          )
        ) : (
          indexedSections.map((section) => (
            <div key={section.title} className="pb-2 last:pb-0">
              <h3 className="px-3 pt-2 pb-1 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                {section.title}
              </h3>
              <div className="space-y-1">
                {section.items.map((item) => (
                  <button
                    key={`${item.type}:${item.id}`}
                    type="button"
                    data-index={item.index}
                    onMouseMove={() => setSelectedIndex(item.index)}
                    onClick={() => openItem(item)}
                    className={cn(
                      'w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-colors',
                      item.index === activeIndex
                        ? 'bg-accent text-accent-foreground'
                        : 'text-foreground/80'
                    )}
                  >
                    <item.icon className="w-4 h-4 shrink-0 text-muted-foreground" />
                    <span className="flex-1 min-w-0">
                      <span className="block text-sm font-medium truncate">{item.label}</span>
                      {item.subtitle && (
                        <span className="block text-xs text-muted-foreground truncate">
                          {item.subtitle}
                        </span>
                      )}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ))
        )}
      </div>

      {/* Footer hints */}
      <div className="flex items-center gap-4 px-5 py-3 border-t border-border/50 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <kbd className={kbdClass}>↑</kbd>
          <kbd className={kbdClass}>↓</kbd>
          <span className="ml-1">Navigate</span>
        </span>
        <span className="flex items-center gap-1">
          <kbd className={kbdClass}>↵</kbd>
          <span className="ml-1">Open</span>
        </span>
        <span className="flex items-center gap-1">
          <kbd className={cn(kbdClass, 'uppercase')}>esc</kbd>
          <span className="ml-1">Close</span>
        </span>
      </div>
    </Modal>
  )
}
