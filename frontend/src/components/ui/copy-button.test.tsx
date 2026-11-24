// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { copyTextToClipboard } from '../../lib/environment-revisions'
import { CopyButton, CopyButtonView } from './copy-button'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('copyTextToClipboard', () => {
  it('writes the full untruncated value', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const value = `sha256:${'a'.repeat(64)}`

    await expect(copyTextToClipboard(value)).resolves.toBe(true)
    expect(writeText).toHaveBeenCalledOnce()
    expect(writeText).toHaveBeenCalledWith(value)
  })

  it('is a no-op when the clipboard is unavailable', async () => {
    vi.stubGlobal('navigator', {})

    await expect(copyTextToClipboard('revision-id')).resolves.toBe(false)
  })

  it('does not throw when clipboard access is rejected', async () => {
    vi.stubGlobal('navigator', {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
    })

    await expect(copyTextToClipboard('revision-id')).resolves.toBe(false)
  })
})

describe('CopyButton', () => {
  it('exposes a descriptive accessible label for copying', () => {
    const html = renderToStaticMarkup(
      <CopyButton value="11111111-1111-4111-8111-111111111111" label="Copy revision ID" />
    )

    expect(html).toContain('aria-label="Copy revision ID"')
    expect(html).toContain('data-state="idle"')
  })

  it('renders copied feedback with a check icon and live status', () => {
    const idle = renderToStaticMarkup(
      <CopyButtonView copied={false} label="Copy revision fingerprint" onCopy={() => undefined} />
    )
    expect(idle).toContain('aria-label="Copy revision fingerprint"')
    expect(idle).toContain('lucide-copy')

    const copied = renderToStaticMarkup(
      <CopyButtonView copied label="Copy revision fingerprint" onCopy={() => undefined} />
    )
    expect(copied).toContain('data-state="copied"')
    expect(copied).toContain('aria-label="Copied"')
    expect(copied).toContain('lucide-check')
    expect(copied).toContain('role="status"')
    expect(copied).toContain('Copied')
  })
})
