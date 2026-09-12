// Типы соответствуют docs/smm-agent/api-contract.md. Контракт заморожен:
// расхождения фиксируются списком, а не правкой этого файла.

export type SlotStatus =
  | 'no_topic'
  | 'planned'
  | 'generating'
  | 'needs_review'
  | 'approved'
  | 'published'
  | 'failed'
  | 'skipped'

export type PublicationMode = 'review' | 'auto'
export type CheckLayer = 'format' | 'rules' | 'grounding' | 'image'
export type OperationPurpose =
  | 'generate'
  | 'judge'
  | 'claims'
  | 'vision'
  | 'caption'
  | 'embedding'
  | 'derive_rules'
export type OperationStatus = 'running' | 'succeeded' | 'failed'
export type RuleSeverity = 'block' | 'warn'
export type RuleOrigin = 'derived' | 'manual'
export type CaptionStatus = 'pending' | 'ready' | 'failed'

export interface User {
  id: number
  telegram_user_id: string
  telegram_username: string | null
  display_name: string
  created_at: string
  common_prompt: string
}

/** Статус запроса на вход через Telegram-бота. */
export type LoginStatus = 'pending' | 'confirmation' | 'approved' | 'denied' | 'expired'

export interface LoginRequest {
  browser_token: string
  telegram_url: string
  expires_at: string
}

export interface LoginStatusResponse {
  status: LoginStatus
  user?: User
  csrf?: string
}

export interface ProjectSummary {
  id: number
  name: string
  channel_title: string | null
  publication_mode: PublicationMode
  counts: { needs_review: number; no_topic: number; planned: number }
}

export interface ProjectChannel {
  configured: boolean
  chat_id: string | null
  status: 'ok' | 'error' | 'unchecked'
  checked_at: string | null
  error?: string | null
}

export interface Project {
  id: number
  name: string
  timezone: string
  language: string
  audience: string
  tone: string
  project_prompt: string
  publication_mode: PublicationMode
  generation_lead_minutes: number
  media_reuse_days: number
  channel: ProjectChannel
  media: { total: number; available: number }
}

export interface Rubric {
  id: number
  name: string
  instructions: string
  enabled: boolean
}

export interface Rule {
  id: number
  text: string
  severity: RuleSeverity
  enabled: boolean
  origin: RuleOrigin
  position: number
}

export interface SlotPostPreview {
  id: number
  title: string
  excerpt: string
  media_thumb_url: string | null
  checks_summary: { passed: boolean; blocking: number; warnings: number }
}

export interface Slot {
  id: number
  publish_at: string
  generate_at: string
  rubric: { id: number; name: string } | null
  topic: string
  status: SlotStatus
  post: SlotPostPreview | null
}

export interface ValidationItem {
  severity?: RuleSeverity
  key?: string
  rule_id?: number
  text?: string
  claim?: string
  asset_id?: number
  passed?: boolean
  verdict?: 'supported' | 'unsupported' | 'contradicted' | 'match' | 'weak' | 'mismatch'
  span?: [number, number]
  detail?: string
  evidence?: string
}

export interface ValidationLayer {
  layer: CheckLayer
  passed: boolean
  score?: string
  items: ValidationItem[]
}

export interface ValidationReport {
  passed: boolean
  iterations: number
  layers: ValidationLayer[]
}

export interface PostMedia {
  asset_id: number
  caption: string
  url: string
  rationale: string
  last_used_at: string | null
}

export interface Post {
  id: number
  slot_id: number
  status: SlotStatus
  post_text: string
  char_count: number
  media: PostMedia | null
  generation: {
    provider: string
    model: string
    reasoning_effort: string
    iterations: number
    generated_at: string
    repair_error?: string
  } | null
  validation: ValidationReport
  published: { published_at: string; message_url: string } | null
}

export interface PostSummary {
  id: number
  slot_id: number
  status: SlotStatus
  title: string
  excerpt: string
  publish_at: string
  rubric: { id: number; name: string } | null
  checks_summary: { passed: boolean; blocking: number; warnings: number }
}

export interface MediaAsset {
  id: number
  url: string
  caption: string | null
  caption_status: CaptionStatus
  width: number
  height: number
  bytes: number
  enabled: boolean
  use_count: number
  last_used_at: string | null
  available: boolean
}

export interface MediaPage {
  items: MediaAsset[]
  next_cursor: string | null
}

export interface Operation {
  operation_id: number
  status: OperationStatus
  purpose?: OperationPurpose
  actor?: 'user' | 'scheduler'
  result?: unknown
  error?: { code: string; message: string } | null
  started_at?: string
  finished_at?: string | null
}

export interface Publication {
  id: number
  post_id: number
  published_at: string
  message_url: string
  status: string
}
