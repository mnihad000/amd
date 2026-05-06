"use client"

import type { RunResource } from "@/lib/dashboard-api"

import { formatDateTime, statusTone } from "@/components/dashboard/format"
import { cn } from "@/lib/utils"

interface RunStatusHeaderProps {
  run: RunResource | null
  cancelling: boolean
  onCancel: () => void
}

export function RunStatusHeader({ run, cancelling, onCancel }: RunStatusHeaderProps) {
  if (!run) {
    return (
      <section className="rounded-[2rem] border border-dashed border-white/12 bg-slate-950/45 p-6 backdrop-blur-xl">
        <p className="text-[0.72rem] font-semibold uppercase tracking-[0.34em] text-cyan-200/70">
          Active Workspace
        </p>
        <h2 className="mt-3 text-2xl font-semibold tracking-[-0.03em] text-white">
          No run selected yet.
        </h2>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300/80">
          Start a run from the composer or reopen a recent run from the rail to inspect lifecycle state,
          stage progress, and artifact output.
        </p>
      </section>
    )
  }

  const canCancel = run.status === "queued" || run.status === "running"
  const summary = run.summary

  return (
    <section className="rounded-[2rem] border border-white/10 bg-slate-950/65 p-6 shadow-[0_24px_90px_rgba(2,6,23,0.45)] backdrop-blur-xl">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-[0.72rem] font-semibold uppercase tracking-[0.34em] text-cyan-200/70">
              Active Workspace
            </p>
            <span className={cn("rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.24em]", statusTone(run.status))}>
              {run.status}
            </span>
          </div>
          <div>
            <h2 className="text-2xl font-semibold tracking-[-0.03em] text-white">{run.prompt}</h2>
            <p className="mt-2 text-sm leading-6 text-slate-300/80">
              {run.classes.join(", ")} • {run.source_mode} source resolution
            </p>
          </div>
        </div>

        <button
          type="button"
          disabled={!canCancel || cancelling}
          onClick={onCancel}
          className={cn(
            "inline-flex items-center justify-center rounded-full px-4 py-2 text-xs font-semibold uppercase tracking-[0.24em] transition",
            canCancel && !cancelling
              ? "border border-rose-300/25 bg-rose-500/10 text-rose-100 hover:bg-rose-500/18"
              : "cursor-not-allowed border border-white/10 bg-white/5 text-slate-400",
          )}
        >
          {cancelling ? "Cancelling" : "Cancel Run"}
        </button>
      </div>

      <div className="mt-6 grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="rounded-[1.5rem] border border-white/10 bg-white/5 p-5">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-300/70">Lifecycle</p>
            <span className="text-xs uppercase tracking-[0.22em] text-slate-400">
              {run.progress.completed_stages}/{run.progress.total_stages} stages complete
            </span>
          </div>

          <div className="mt-3 overflow-hidden rounded-full bg-white/8">
            <div
              className="h-2 rounded-full bg-gradient-to-r from-cyan-400 via-sky-400 to-emerald-400 transition-[width] duration-500"
              style={{ width: `${Math.max(run.progress.percent, run.status === "running" ? 6 : 0)}%` }}
            />
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Current stage" value={run.current_stage ?? "Queued"} />
            <StatCard label="Updated" value={formatDateTime(run.updated_at)} />
            <StatCard label="Created" value={formatDateTime(run.created_at)} />
            <StatCard
              label="Cancel flag"
              value={run.cancel_requested ? "Requested" : "Clear"}
            />
          </div>
        </div>

        <div className="rounded-[1.5rem] border border-white/10 bg-white/5 p-5">
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-300/70">
            Top-line Outcome
          </p>
          {summary ? (
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <OutcomeCard label="Admitted" count={summary.admitted_classes.length} tone="emerald" />
              <OutcomeCard label="Deferred" count={summary.deferred_classes.length} tone="amber" />
              <OutcomeCard label="Blocked" count={summary.blocked_classes.length} tone="rose" />
            </div>
          ) : (
            <p className="mt-4 text-sm leading-6 text-slate-300/75">
              Summary fields will populate once the run reaches a terminal state.
            </p>
          )}

          {run.error ? (
            <div className="mt-4 rounded-[1.2rem] border border-rose-400/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
              <div className="font-semibold uppercase tracking-[0.18em]">{run.error.code}</div>
              <p className="mt-1 text-sm leading-6 text-rose-50/90">{run.error.message}</p>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  )
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[1.2rem] border border-white/8 bg-slate-950/45 px-4 py-3">
      <div className="text-[0.68rem] font-semibold uppercase tracking-[0.26em] text-slate-400">{label}</div>
      <div className="mt-2 text-sm font-medium text-white">{value}</div>
    </div>
  )
}

function OutcomeCard({
  label,
  count,
  tone,
}: {
  label: string
  count: number
  tone: "emerald" | "amber" | "rose"
}) {
  const toneClassName =
    tone === "emerald"
      ? "border-emerald-400/20 bg-emerald-500/10 text-emerald-100"
      : tone === "amber"
        ? "border-amber-300/20 bg-amber-400/10 text-amber-100"
        : "border-rose-400/20 bg-rose-500/10 text-rose-100"

  return (
    <div className={cn("rounded-[1.2rem] border px-4 py-4", toneClassName)}>
      <div className="text-[0.68rem] font-semibold uppercase tracking-[0.26em]">{label}</div>
      <div className="mt-2 text-3xl font-semibold tracking-[-0.04em]">{count}</div>
    </div>
  )
}
