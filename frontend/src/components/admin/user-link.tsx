// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { Link } from '@tanstack/react-router'
import { cn } from '../../lib/utils'

const SIZES = {
  sm: { box: 'w-6 h-6', text: 'text-[10px]', label: 'text-sm' },
  md: { box: 'w-8 h-8', text: 'text-xs', label: 'text-sm' },
  lg: { box: 'w-9 h-9', text: 'text-xs', label: 'text-sm' },
} as const

interface UserLinkProps {
  userId: string
  /** Primary display text (e.g. username or display name). */
  name: string
  /** Secondary line shown under the name (e.g. display name when name is username). */
  secondary?: string | null
  avatarUrl?: string | null
  size?: keyof typeof SIZES
  className?: string
}

/** Avatar + name linking to the admin user detail page (/admin/users/$userId). */
export function UserLink({
  userId,
  name,
  secondary,
  avatarUrl,
  size = 'md',
  className,
}: UserLinkProps) {
  const s = SIZES[size]
  return (
    <Link
      to="/admin/users/$userId"
      params={{ userId }}
      className={cn(
        'inline-flex items-center gap-2 hover:text-primary transition-colors group',
        className
      )}
    >
      {avatarUrl ? (
        <img src={avatarUrl} alt={name} className={cn('rounded-full shrink-0', s.box)} />
      ) : (
        <div
          className={cn(
            'rounded-full bg-primary/10 flex items-center justify-center shrink-0',
            s.box
          )}
        >
          <span className={cn('font-medium text-primary', s.text)}>
            {name.slice(0, 2).toUpperCase()}
          </span>
        </div>
      )}
      <span className="min-w-0">
        <span className={cn('block font-medium truncate group-hover:underline', s.label)}>
          {name}
        </span>
        {secondary && (
          <span className="block text-xs text-muted-foreground truncate">{secondary}</span>
        )}
      </span>
    </Link>
  )
}
