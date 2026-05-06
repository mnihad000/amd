"use client"

import type { RunResource } from "@/lib/dashboard-api"

import { formatDateTime, statusTone } from "@/components/dashboard/format"
import { cn } from "@/lib/utils"

interface RecentRunsListProps {
  runs: RunResource[]
  activeJobId: string | null
  onSelect: (jobId: string) => void
}

export function RecentRunsList({ runs, activeJobId, onSelect }: RecentRunsListProps) {
  return (
    <section className="rounded-[2rem] border border-white/10 bg-slate-950/65 p-6 shadow-[0_24px_90px_rgba(2,6,23,0.45)] backdrop-blur-xl">
      <div className="mb-5 space-y-2">
        <p className="text-[0.72rem] font-semibold uppercase tracking-[0.34em] text-cyan-200/70">
          Recent Runs
        </p>
        <h3 className="text-xl font-semibold tracking-[-0.03em] text-white">Latest queue and terminal history.</h3>
      </div>

      {runs.length ? (
        <div className="space-y-3">
          {runs.map((run) => {
            const selected = run.job_id === activeJobId
            return (
              <button
                key={run.job_id}
                type="button"
                onClick={() => onSelect(run.job_id)}
                className={cn(
                  "w-full rounded-[1.35rem] border px-4 py-4 text-left transition",
                  selected
                    ? "border-cyan-300/35 bg-cyan-400/10 shadow-[0_0_0_1px_rgba(125,211,252,0.08)]"
                    : "border-white/10 bg-white/5 hover:border-white/20 hover:bg-white/8",
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-white">{run.prompt}</div>
                    <div className="mt-2 text-xs uppercase tracking-[0.22em] text-slate-400">{run.job_id}</div>
                  </div>
                  <span className={cn("shrink-0 rounded-full border px-2.5 py-1 text-[0.64rem] font-semibold uppercase tracking-[0.2em]", statusTone(run.status))}>
                    {run.status}
                  </span>
                </div>

                <div className="mt-4 flex items-center justify-between gap-3 text-xs text-slate-300/75">
                  <span>{run.current_stage ?? "terminal"}</span>
                  <span>{formatDateTime(run.updated_at)}</span>
                </div>
              </button>
            )
          })}
        </div>
      ) : (
        <p className="text-sm leading-6 text-slate-300/75">No recorded runs yet.</p>
      )}
    </section>
  )
}
