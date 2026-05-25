export type RunStatus = "queued" | "running" | "completed" | "failed"
export type StageStatus = "pending" | "running" | "completed" | "failed" | "skipped"
export type SourceMode = "manifest" | "live"

export interface RunError {
  code: string
  message: string
}

export interface StageHistoryEntry {
  name: string
  status: StageStatus
  started_at: string | null
  completed_at: string | null
  duration_ms: number | null
}

export interface RunProgress {
  total_stages: number
  completed_stages: number
  skipped_stages: number
  failed_stages: number
  percent: number
}

export interface RunSummaryPayload {
  job_id: string
  prompt: string
  requested_classes: string[]
  admitted_classes: string[]
  deferred_classes: string[]
  blocked_classes: string[]
  source_breakdown: Record<string, number>
  budgets: Record<string, number>
  notes: string[]
  artifact_paths: Record<string, string>
  per_class_counts?: Record<string, Record<string, number>>
  review_queue_summary?: Record<string, number>
  iteration_policy?: Record<string, unknown>
  baseline_comparison_summary?: Record<string, unknown>
  promotion_guard_summary?: Record<string, unknown>
  governance_summary?: Record<string, unknown>
  lineage_summary?: Record<string, number>
  license_compliance?: { export_status?: string; summary?: Record<string, number> }
  monitoring_summary?: MonitoringSummary
  orchestration_resilience?: OrchestrationResilience
}

export interface MonitoringSummary {
  enabled?: boolean
  correlation_key?: string
  prometheus?: { metric_count?: number; scrape_artifact?: string }
  loki?: { log_count?: number; log_artifact?: string }
  grafana?: { dashboard_artifact?: string; alert_policy_artifact?: string }
  alerts?: { status?: string; triggered_count?: number; critical_count?: number; warning_count?: number; error_count?: number }
}

export interface OrchestrationResilience {
  enabled?: boolean
  retry?: { max_stage_attempts?: number; checkpoint_count?: number; next_resume_stage?: string | null }
  dead_letter?: { status?: string; stage?: string | null }
  rollback?: { status?: string; last_stable_job_id?: string | null }
  concurrency?: { backpressure_state?: string; queue_limit?: number; queued_count?: number; active_count?: number }
  sla?: { overall_state?: string; stage_states?: Record<string, { state?: string; escalation?: string }> }
}

export interface RunResource {
  job_id: string
  status: RunStatus
  prompt: string
  classes: string[]
  source_mode: SourceMode
  current_stage: string | null
  cancel_requested: boolean
  created_at: string
  updated_at: string
  error: RunError | null
  summary: RunSummaryPayload | null
  monitoring_summary: MonitoringSummary | null
  orchestration_resilience: OrchestrationResilience | null
  stage_history: StageHistoryEntry[]
  progress: RunProgress
}

export interface RunListResponse {
  runs: RunResource[]
}

export interface ArtifactDescriptor {
  path: string
  api_url: string
  file_url: string | null
  exists: boolean
}

export interface ArtifactsResponse {
  job_id: string
  status: "completed"
  artifact_paths: Record<string, string>
  artifacts: Record<string, ArtifactDescriptor>
}

export interface HealthResponse {
  status: "ready" | "draining"
  accepting_runs: boolean
  active_worker_count: number
  queued_run_count: number
  artifacts_root: string
  index_path: string
}

export interface RunCreateRequest {
  prompt: string
  classes: string[]
  source_mode: SourceMode
  output_root?: string
  env_file?: string
}

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "")

function buildUrl(path: string): string {
  return `${API_BASE_URL}${path}`
}

function encodePath(path: string): string {
  return path
    .split("/")
    .filter(Boolean)
    .map((segment) => encodeURIComponent(segment))
    .join("/")
}

async function readJson<T>(response: Response): Promise<T> {
  return (await response.json()) as T
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(buildUrl(path), {
    cache: "no-store",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  })

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { error?: { code?: string; message?: string } }
      | null
    throw new Error(payload?.error?.message ?? `Request failed with status ${response.status}.`)
  }

  return readJson<T>(response)
}

export function normalizeRunFilePath(jobId: string, rawPath: string): string | null {
  const normalized = rawPath.replace(/\\/g, "/").replace(/^file:\/+/, "")
  const marker = `/${jobId}/`
  const markerIndex = normalized.lastIndexOf(marker)

  if (markerIndex >= 0) {
    return normalized.slice(markerIndex + marker.length)
  }

  if (normalized.startsWith(`${jobId}/`)) {
    return normalized.slice(jobId.length + 1)
  }

  if (!normalized.startsWith("/") && !/^[a-zA-Z]:\//.test(normalized)) {
    return normalized
  }

  return null
}

export function toRunFileUrl(jobId: string, rawPath: string): string | null {
  const relativePath = normalizeRunFilePath(jobId, rawPath)
  if (!relativePath) {
    return null
  }
  return buildUrl(`/runs/${encodeURIComponent(jobId)}/files/${encodePath(relativePath)}`)
}

export async function createRun(payload: RunCreateRequest): Promise<RunResource> {
  return requestJson<RunResource>("/runs", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export async function getRun(jobId: string): Promise<RunResource> {
  return requestJson<RunResource>(`/runs/${encodeURIComponent(jobId)}`)
}

export async function listRuns(limit = 10): Promise<RunListResponse> {
  return requestJson<RunListResponse>(`/runs?limit=${limit}`)
}

export async function cancelRun(jobId: string): Promise<RunResource> {
  return requestJson<RunResource>(`/runs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  })
}

export async function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/health")
}

export async function getArtifacts(jobId: string): Promise<ArtifactsResponse> {
  return requestJson<ArtifactsResponse>(`/runs/${encodeURIComponent(jobId)}/artifacts`)
}

export async function getArtifactJson<T>(jobId: string, artifactName: string): Promise<T> {
  return requestJson<T>(`/runs/${encodeURIComponent(jobId)}/artifacts/${encodeURIComponent(artifactName)}`)
}
