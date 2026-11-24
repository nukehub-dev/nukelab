// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

export type EnvironmentRevisionPortability = 'registry_verified' | 'local_only'
export type EnvironmentRevisionVolumeMode = 'read_only' | 'read_write'

export interface EnvironmentRevisionImage {
  registry_verified: boolean
  os: string | null
  architecture: string | null
  variant: string | null
  verified_reference: string | null
  manifest_digest: string | null
  index_digest: string | null
  descriptor_media_type: string | null
}

export interface EnvironmentRevisionVolume {
  mount_path: string
  mode: EnvironmentRevisionVolumeMode
}

export interface EnvironmentRevisionConfiguration {
  image: string | null
  tool_image: string | null
  packages: string[]
  ports: string[]
  tool_mounts: string[]
  environment_variable_names: string[]
  volumes: EnvironmentRevisionVolume[]
}

export interface EnvironmentRevisionSummary {
  id: string
  template_id: string
  fingerprint: string
  portable_fingerprint: string | null
  portability: EnvironmentRevisionPortability
  revoked: boolean
  created_at: string | null
  runtime: EnvironmentRevisionImage
  toolchain: EnvironmentRevisionImage | null
  configuration: EnvironmentRevisionConfiguration
  limitations: string[]
}

export interface EnvironmentRevisionPagination {
  limit: number
  offset: number
  total: number
  has_more: boolean
}

export interface EnvironmentRevisionPage {
  items: EnvironmentRevisionSummary[]
  pagination: EnvironmentRevisionPagination
}

export interface VerifyEnvironmentArtifactsResponse {
  success: true
  data: EnvironmentRevisionSummary
}

export interface RevokeEnvironmentRevisionResponse {
  success: true
  data: EnvironmentRevisionSummary
  template_has_selectable_revision: boolean
  selectable_revision_count: number
  already_revoked: boolean
}
