"use client"

import type { RunResource } from "@/lib/dashboard-api"

import { formatDateTime, formatDuration, stageTone } from "@/components/dashboard/format"
import { cn } from "@/lib/utils"

interface StageTimelineProps {
  run: RunResource | null
}

export function StageTimeline({ run }: StageTimelineProps) {
  return (
    <section className="rounded-[2rem] border border-white/10 bg-slate-950/65 p-6 shadow-[0_24px_90px_rgba(2,6,23,0.45)] backdrop-blur-xl">
      <div className="mb-5 space-y-2">
        <p className="text-[0.72rem] font-semibold uppercase tracking-[0.34em] text-cyan-200/70">
          Stage Timeline
        </p>
        <h3 className="text-xl font-semibold tracking-[-0.03em] text-white">Stage-by-stage run trace.</h3>
      </div>

      {run ? (
        <div className="space-y-3">
          {run.stage_history.map((stage, index) => (
            <div
              key={stage.name}
              className={cn(
                "rounded-[1.3rem] border px-4 py-4 transition",
                stageTone(stage.status),
              )}
            >
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="text-[0.66rem] font-semibold uppercase tracking-[0.26em] text-slate-300/75">
                    Stage {String(index + 1).padStart(2, "0")}
                  </div>
                  <h4 className="mt-1 text-base font-semibold capitalize text-white">
                    {stage.name.replaceAll("_", " ")}
                  </h4>
                </div>

                <span className="text-xs font-semibold uppercase tracking-[0.22em] text-inherit/85">
                  {stage.status}
                </span>
              </div>

              <div className="mt-4 grid gap-3 text-sm text-slate-200/80 sm:grid-cols-3">
                <TimelineMeta label="Started" value={formatDateTime(stage.started_at)} />
                <TimelineMeta label="Completed" value={formatDateTime(stage.completed_at)} />
                <TimelineMeta label="Duration" value={formatDuration(stage.duration_ms)} />
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm leading-6 text-slate-300/75">
          The operator timeline appears after a run is selected.
        </p>
      )}
    </section>
  )
}

function TimelineMeta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[1rem] border border-white/8 bg-slate-950/45 px-3 py-3">
      <div className="text-[0.62rem] font-semibold uppercase tracking-[0.24em] text-slate-400">{label}</div>
      <div className="mt-1 text-sm text-white">{value}</div>
    </div>
  )
}
