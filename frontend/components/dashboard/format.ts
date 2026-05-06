import type { RunStatus, StageStatus } from "@/lib/dashboard-api"

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "Not available"
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date)
}

export function formatDuration(durationMs: number | null | undefined): string {
  if (durationMs == null) {
    return "In flight"
  }

  if (durationMs < 1000) {
    return `${durationMs}ms`
  }

  const seconds = durationMs / 1000
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`
  }

  return `${(seconds / 60).toFixed(1)}m`
}

export function formatMetric(value: number | null | undefined): string {
  if (value == null) {
    return "Unavailable"
  }
  return value.toFixed(3)
}

export function statusTone(status: RunStatus): string {
  switch (status) {
    case "completed":
      return "border-emerald-400/30 bg-emerald-500/12 text-emerald-100"
    case "failed":
      return "border-rose-400/30 bg-rose-500/12 text-rose-100"
    case "running":
      return "border-cyan-300/30 bg-cyan-400/12 text-cyan-100"
    case "queued":
      return "border-amber-300/30 bg-amber-400/12 text-amber-100"
  }
}

export function stageTone(status: StageStatus): string {
  switch (status) {
    case "completed":
      return "border-emerald-400/25 bg-emerald-500/12 text-emerald-100"
    case "failed":
      return "border-rose-400/25 bg-rose-500/12 text-rose-100"
    case "running":
      return "border-cyan-300/25 bg-cyan-400/12 text-cyan-100"
    case "skipped":
      return "border-slate-400/20 bg-slate-500/10 text-slate-200"
    case "pending":
      return "border-white/10 bg-white/5 text-slate-300"
  }
}
