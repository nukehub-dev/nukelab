// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Canonical external NukeHub destinations. Keep these as the single source
 * of truth so the support page, sidebar, and login page never drift.
 */
export const EXTERNAL_LINKS = {
  community: {
    label: 'NukeTalk Community',
    shortLabel: 'Community',
    url: 'https://talk.nukehub.org',
    description: 'Ask questions, share results, and discuss with other NukeHub users.',
  },
  contact: {
    label: 'Contact Us',
    shortLabel: 'Contact',
    url: 'https://nukehub.org/contact',
    description: 'Reach the NukeHub team for general inquiries and support.',
  },
  blog: {
    label: 'Blog & Updates',
    shortLabel: 'Blog',
    url: 'https://blog.nukehub.org',
    description: 'News, tutorials, and updates from the NukeHub community.',
  },
} as const
