"use client"

import type { ReactNode } from "react"

import type { RunResource } from "@/lib/dashboard-api"

import { formatMetric } from "@/components/dashboard/format"
import type { ArtifactDataBundle, ClassPlanEntry, PreviewSample } from "@/components/dashboard/types"
import { toRunFileUrl } from "@/lib/dashboard-api"
import { cn } from "@/lib/utils"

interface ArtifactPanelsProps {
  run: RunResource | null
  artifactData: ArtifactDataBundle | null
  artifactError: string | null
}

export function ArtifactPanels({ run, artifactData, artifactError }: ArtifactPanelsProps) {
  if (!run) {
    return (
      <section className="rounded-[2rem] border border-white/10 bg-slate-950/65 p-6 shadow-[0_24px_90px_rgba(2,6,23,0.45)] backdrop-blur-xl">
        <p className="text-[0.72rem] font-semibold uppercase tracking-[0.34em] text-cyan-200/70">
          Artifact Preview
        </p>
        <p className="mt-4 text-sm leading-6 text-slate-300/75">
          Select a run to inspect admission outcomes, evaluation signals, and frame-level previews.
        </p>
      </section>
    )
  }

  if (run.status !== "completed") {
    return (
      <section className="rounded-[2rem] border border-white/10 bg-slate-950/65 p-6 shadow-[0_24px_90px_rgba(2,6,23,0.45)] backdrop-blur-xl">
        <p className="text-[0.72rem] font-semibold uppercase tracking-[0.34em] text-cyan-200/70">
          Artifact Preview
        </p>
        <p className="mt-4 text-sm leading-6 text-slate-300/75">
          Artifact panels unlock when the run completes. Until then, the workspace reflects lifecycle and stage
          progress only.
        </p>
      </section>
    )
  }

  if (artifactError) {
    return (
      <section className="rounded-[2rem] border border-rose-400/20 bg-rose-500/10 p-6 shadow-[0_24px_90px_rgba(2,6,23,0.35)] backdrop-blur-xl">
        <p className="text-[0.72rem] font-semibold uppercase tracking-[0.34em] text-rose-100/80">
          Artifact Preview
        </p>
        <p className="mt-4 text-sm leading-6 text-rose-50/90">{artifactError}</p>
      </section>
    )
  }

  if (!artifactData) {
    return (
      <section className="rounded-[2rem] border border-white/10 bg-slate-950/65 p-6 shadow-[0_24px_90px_rgba(2,6,23,0.45)] backdrop-blur-xl">
        <p className="text-[0.72rem] font-semibold uppercase tracking-[0.34em] text-cyan-200/70">
          Artifact Preview
        </p>
        <p className="mt-4 text-sm leading-6 text-slate-300/75">Loading artifact snapshots for this run.</p>
      </section>
    )
  }

  const classPlan = artifactData.classPlan
  const acceptedPreview = artifactData.acceptedFrames.slice(0, 4).map((sample) => ({
    id: sample.id,
    title: sample.class_names.join(", "),
    imageUrl: toRunFileUrl(run.job_id, sample.path),
    meta: sample.source_type,
    note: sample.quality_score != null ? `quality ${sample.quality_score.toFixed(3)}` : undefined,
  }))

  const sampleById = new Map(artifactData.sampleManifest.map((sample) => [sample.id, sample]))
  const rejectedPreview = artifactData.frameScores
    .filter((entry) => entry.decision !== "accept")
    .map((entry): PreviewSample | null => {
      const sample = sampleById.get(entry.sample_id)
      if (!sample) {
        return null
      }
      return {
        id: sample.id,
        title: sample.class_names.join(", "),
        imageUrl: toRunFileUrl(run.job_id, sample.path),
        meta: sample.source_type,
        note: entry.rejection_reasons[0] ?? "Rejected",
      }
    })
    .filter((entry): entry is PreviewSample => entry !== null)
    .slice(0, 4)

  return (
    <section className="rounded-[2rem] border border-white/10 bg-slate-950/65 p-6 shadow-[0_24px_90px_rgba(2,6,23,0.45)] backdrop-blur-xl">
      <div className="mb-6 space-y-2">
        <p className="text-[0.72rem] font-semibold uppercase tracking-[0.34em] text-cyan-200/70">
          Artifact Preview
        </p>
        <h3 className="text-xl font-semibold tracking-[-0.03em] text-white">
          Completion snapshot and frame curation evidence.
        </h3>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <ArtifactCard title="Class summary">
          <div className="grid gap-3 sm:grid-cols-3">
            <SummaryChip label="Admitted" items={run.summary?.admitted_classes ?? []} tone="emerald" />
            <SummaryChip label="Deferred" items={run.summary?.deferred_classes ?? []} tone="amber" />
            <SummaryChip label="Blocked" items={run.summary?.blocked_classes ?? []} tone="rose" />
          </div>
          <div className="mt-4 space-y-3">
            {classPlan.slice(0, 4).map((entry) => (
              <ClassRow key={entry.name} entry={entry} />
            ))}
          </div>
        </ArtifactCard>

        <ArtifactCard title="Evaluation report">
          <div className="grid gap-3 sm:grid-cols-3">
            <MetricTile label="mAP@50" value={formatMetric(artifactData.evaluationReport?.map50)} />
            <MetricTile label="Precision" value={formatMetric(artifactData.evaluationReport?.precision)} />
            <MetricTile label="Recall" value={formatMetric(artifactData.evaluationReport?.recall)} />
          </div>
          <div className="mt-4 space-y-2 text-sm leading-6 text-slate-200/80">
            {(artifactData.evaluationReport?.notes ?? run.summary?.notes ?? []).slice(0, 4).map((note) => (
              <div key={note} className="rounded-[1rem] border border-white/8 bg-slate-950/45 px-3 py-3">
                {note}
              </div>
            ))}
          </div>
        </ArtifactCard>

        <ArtifactCard title="Accepted frame samples">
          <PreviewGrid samples={acceptedPreview} emptyMessage="No accepted frame previews were available." />
        </ArtifactCard>

        <ArtifactCard title="Rejected frame samples">
          <PreviewGrid samples={rejectedPreview} emptyMessage="No rejected frame samples were surfaced." />
        </ArtifactCard>
      </div>

      <ArtifactCard title="Artifact availability" className="mt-4">
        <div className="grid gap-3 lg:grid-cols-2">
          {Object.entries(artifactData.artifacts?.artifacts ?? {}).map(([artifactName, descriptor]) => (
            <div
              key={artifactName}
              className="rounded-[1.1rem] border border-white/8 bg-slate-950/45 px-4 py-3"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm font-semibold text-white">{artifactName}</span>
                <span
                  className={cn(
                    "rounded-full border px-2.5 py-1 text-[0.62rem] font-semibold uppercase tracking-[0.2em]",
                    descriptor.exists
                      ? "border-emerald-400/20 bg-emerald-500/10 text-emerald-100"
                      : "border-amber-300/20 bg-amber-400/10 text-amber-100",
                  )}
                >
                  {descriptor.exists ? "ready" : "missing"}
                </span>
              </div>
              <div className="mt-2 break-all text-xs leading-5 text-slate-400">{descriptor.path}</div>
            </div>
          ))}
        </div>
      </ArtifactCard>
    </section>
  )
}

function ArtifactCard({
  title,
  className,
  children,
}: {
  title: string
  className?: string
  children: ReactNode
}) {
  return (
    <div className={cn("rounded-[1.6rem] border border-white/10 bg-white/5 p-5", className)}>
      <div className="mb-4 text-sm font-semibold uppercase tracking-[0.24em] text-slate-300/75">{title}</div>
      {children}
    </div>
  )
}

function SummaryChip({
  label,
  items,
  tone,
}: {
  label: string
  items: string[]
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
      <div className="text-[0.66rem] font-semibold uppercase tracking-[0.24em]">{label}</div>
      <div className="mt-2 text-2xl font-semibold tracking-[-0.04em]">{items.length}</div>
      <div className="mt-2 text-xs leading-5 text-inherit/80">{items.join(", ") || "None"}</div>
    </div>
  )
}

function ClassRow({ entry }: { entry: ClassPlanEntry }) {
  return (
    <div className="rounded-[1rem] border border-white/8 bg-slate-950/45 px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-semibold text-white">{entry.name}</span>
        <span className="text-[0.66rem] uppercase tracking-[0.22em] text-slate-300/75">{entry.final_state}</span>
      </div>
      <div className="mt-2 text-xs leading-5 text-slate-400">
        {entry.reasons[0] ?? "No note recorded."}
      </div>
    </div>
  )
}

function MetricTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[1.2rem] border border-white/8 bg-slate-950/45 px-4 py-4">
      <div className="text-[0.66rem] font-semibold uppercase tracking-[0.24em] text-slate-400">{label}</div>
      <div className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-white">{value}</div>
    </div>
  )
}

function PreviewGrid({
  samples,
  emptyMessage,
}: {
  samples: PreviewSample[]
  emptyMessage: string
}) {
  if (!samples.length) {
    return <p className="text-sm leading-6 text-slate-300/75">{emptyMessage}</p>
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {samples.map((sample) => (
        <div key={sample.id} className="overflow-hidden rounded-[1.2rem] border border-white/8 bg-slate-950/45">
          <div className="aspect-[4/3] bg-slate-900">
            {sample.imageUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={sample.imageUrl} alt={sample.title} className="h-full w-full object-cover" loading="lazy" />
            ) : (
              <div className="flex h-full items-center justify-center px-6 text-center text-xs uppercase tracking-[0.24em] text-slate-500">
                preview unavailable
              </div>
            )}
          </div>
          <div className="space-y-1 px-4 py-3">
            <div className="text-sm font-semibold text-white">{sample.title}</div>
            <div className="text-xs uppercase tracking-[0.2em] text-slate-400">{sample.meta}</div>
            {sample.note ? <div className="text-xs leading-5 text-slate-300/75">{sample.note}</div> : null}
          </div>
        </div>
      ))}
    </div>
  )
}
