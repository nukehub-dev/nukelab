// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { describe, expect, it } from 'vitest'
import {
  blankVolumeChoices,
  buildExplicitBindings,
  parseManifestInput,
  provenanceErrorMessage,
  recreationReason,
} from './server-provenance'
import type { VolumeRequirement } from '../types/server-provenance'

const requirements: VolumeRequirement[] = [
  { purpose: 'home', mount_path: '/home/owner', mode: 'read_write' },
]

describe('untrusted environment input', () => {
  it('only parses bounded current-version objects before server approval', () => {
    expect(
      parseManifestInput('{"schema_version":"nukelab.environment/v1","runtime":{"untrusted":true}}')
    ).toMatchObject({ runtime: { untrusted: true } })
    expect(() => parseManifestInput('null')).toThrow('JSON object')
    expect(() => parseManifestInput('[]')).toThrow('JSON object')
    expect(() => parseManifestInput('{')).toThrow('valid environment JSON')
    expect(() => parseManifestInput('{"schema_version":"newer/v2"}')).toThrow('not supported')
  })
  it('bounds UTF-8 bytes rather than only characters', () => {
    expect(() =>
      parseManifestInput(
        JSON.stringify({ schema_version: 'nukelab.environment/v1', text: '界'.repeat(22000) })
      )
    ).toThrow('64 KiB')
  })
})

describe('deliberate volume binding', () => {
  it('never initializes source volume IDs or silently chooses fresh volumes', () => {
    expect(blankVolumeChoices(requirements)).toEqual([{ selection: '', sizeGiB: '' }])
    expect(() => buildExplicitBindings(requirements, blankVolumeChoices(requirements), [])).toThrow(
      'every mount'
    )
  })
  it('preserves validated path/mode with explicit auto-create size', () => {
    expect(
      buildExplicitBindings(requirements, [{ selection: 'fresh', sizeGiB: '1.5' }], [])
    ).toEqual([
      { volume_id: '', mount_path: '/home/owner', mode: 'read_write', max_size_bytes: 1610612736 },
    ])
    for (const sizeGiB of ['', '0', '-1', 'Infinity', 'no'])
      expect(() =>
        buildExplicitBindings(requirements, [{ selection: 'fresh', sizeGiB }], [])
      ).toThrow('positive size')
  })
  it('rejects stale selections and mismatched requirement counts', () => {
    expect(() => buildExplicitBindings(requirements, [], [])).toThrow('Validate')
    expect(() =>
      buildExplicitBindings(requirements, [{ selection: 'foreign-or-deleted', sizeGiB: '' }], [])
    ).toThrow('unavailable')
  })
  it('uses safe feature messages without echoing private backend details', () => {
    const error = Object.assign(new Error('raw private config'), { code: 'invalid_manifest' })
    expect(provenanceErrorMessage(error)).toContain('approved revision')
    expect(provenanceErrorMessage(error)).not.toContain('private config')
    expect(recreationReason('source_not_owned')).toContain('owner')
  })
})
