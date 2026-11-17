// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

export interface ImageIdentity {
  requested_reference: string
  local_id: string
  repository_digests: string[]
  os: string
  architecture: string
  registry_verified: boolean
  verified_reference: string | null
  manifest_digest?: string | null
  index_digest?: string | null
  descriptor_media_type?: string | null
}

export interface VolumeRequirement {
  purpose: string
  mount_path: string
  mode: 'read_only' | 'read_write'
}

export interface EnvironmentManifest {
  schema_version: 'nukelab.environment/v1'
  revision_id: string
  revision_fingerprint: string
  template_label: string
  runtime: ImageIdentity
  toolchain: ImageIdentity | null
  toolchain_mounts: string[]
  environment_variable_names: string[]
  environment_values: 'manual_input_required'
  resources: { cpu: number; memory_mib: number; disk_mib: number; gpu_count: number }
  volume_requirements: VolumeRequirement[]
  portability: 'local_only' | 'registry_verified'
  limitations: string[]
}

export interface ServerProvenance {
  state: 'unrecorded' | 'recorded'
  launch_id: string | null
  generation: number | null
  captured_at: string | null
  manifest: EnvironmentManifest | null
  actual_runtime: ImageIdentity | null
  actual_toolchain: ImageIdentity | null
  can_recreate: boolean
  recreation_reason_code: string | null
}

export type RecreationSource =
  | { source_launch_id: string; manifest?: never }
  | { manifest: Record<string, unknown>; source_launch_id?: never }

export interface RecreationPreview {
  manifest: EnvironmentManifest
  environment_label: string
  volume_requirements: VolumeRequirement[]
}

export interface ExplicitVolumeBinding {
  volume_id: string
  mount_path: string
  mode: 'read_only' | 'read_write'
  max_size_bytes?: number
}

export type RecreationRequest = RecreationSource & {
  name: string
  plan_id: string
  volume_mounts: ExplicitVolumeBinding[]
}
