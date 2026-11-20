// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import type { Volume } from '../hooks/use-volumes'
import type { ExplicitVolumeBinding, VolumeRequirement } from '../types/server-provenance'

export const MANIFEST_MAX_BYTES = 65_536

export function parseManifestInput(raw: string): Record<string, unknown> {
  if (new TextEncoder().encode(raw).byteLength > MANIFEST_MAX_BYTES) {
    throw new Error('Environment files must be 64 KiB or smaller.')
  }
  let data: unknown
  try {
    data = JSON.parse(raw)
  } catch {
    throw new Error('Enter a valid environment JSON file.')
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('An environment file must contain a JSON object.')
  }
  if (!('schema_version' in data) || data.schema_version !== 'nukelab.environment/v1') {
    throw new Error('This environment file version is not supported.')
  }
  return data as Record<string, unknown>
}

export interface VolumeChoice {
  selection: string
  sizeGiB: string
}

export function blankVolumeChoices(requirements: VolumeRequirement[]): VolumeChoice[] {
  return requirements.map(() => ({ selection: '', sizeGiB: '' }))
}

export function buildExplicitBindings(
  requirements: VolumeRequirement[],
  choices: VolumeChoice[],
  volumes: Volume[]
): ExplicitVolumeBinding[] {
  if (!requirements.length || requirements.length !== choices.length) {
    throw new Error('Validate the environment before choosing its data volumes.')
  }
  return requirements.map((requirement, index) => {
    const choice = choices[index]
    if (!choice.selection) throw new Error('Choose a fresh or existing volume for every mount.')
    if (choice.selection === 'fresh') {
      const bytes = Math.ceil(Number(choice.sizeGiB) * 1024 ** 3)
      if (!Number.isSafeInteger(bytes) || bytes <= 0) {
        throw new Error('Enter a positive size for each fresh volume.')
      }
      return {
        volume_id: '',
        mount_path: requirement.mount_path,
        mode: requirement.mode,
        max_size_bytes: bytes,
      }
    }
    const volume = volumes.find((item) => item.id === choice.selection && item.status === 'active')
    if (!volume) throw new Error('A selected volume is unavailable. Refresh the volume choices.')
    return { volume_id: volume.id, mount_path: requirement.mount_path, mode: requirement.mode }
  })
}

const errors: Record<string, string> = {
  invalid_manifest: 'The environment file is invalid or does not match an approved revision.',
  source_unrecorded: 'This server has no captured environment to recreate.',
  unrecorded: 'This server has no captured environment to recreate.',
  source_launch_not_found: 'The captured source launch is unavailable to this account.',
  source_not_owned: 'Recreation from a launch is available only to its owner.',
  revision_unavailable: 'The approved environment revision is unavailable or has been revoked.',
  artifact_missing:
    'A captured image is unavailable. This environment cannot be substituted with a newer image.',
  permission_revoked: 'You no longer have access to this approved environment.',
  unsupported_manifest: 'This environment file version is not supported.',
  volume_bindings_mismatch:
    'Choose a volume for each validated mount without changing its path or access mode.',
  invalid_volume_requirement: 'This environment has unsupported data mount requirements.',
  provenance_unavailable: 'Recorded environment details are temporarily unavailable.',
  volume_requirements_mismatch:
    'Choose a volume for each validated mount without changing its path or access mode.',
}

export function provenanceErrorMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'code' in error && typeof error.code === 'string') {
    const message = errors[error.code]
    if (message) return message
  }
  return error instanceof Error ? error.message : 'Environment details are temporarily unavailable.'
}

export function recreationReason(code: string | null): string {
  return code && errors[code]
    ? errors[code]
    : 'Recreation is unavailable under the current environment permissions.'
}
