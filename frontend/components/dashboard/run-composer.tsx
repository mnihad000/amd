"use client"

import type { FormEvent } from "react"

import type { SourceMode } from "@/lib/dashboard-api"
import { cn } from "@/lib/utils"

interface RunComposerProps {
  prompt: string
  classesValue: string
  sourceMode: SourceMode
  submitting: boolean
  error: string | null
  onPromptChange: (value: string) => void
  onClassesChange: (value: string) => void
  onSourceModeChange: (value: SourceMode) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
}

export function RunComposer({
  prompt,
  classesValue,
  sourceMode,
  submitting,
  error,
  onPromptChange,
  onClassesChange,
  onSourceModeChange,
  onSubmit,
}: RunComposerProps) {
  return (
    <section className="rounded-[2rem] border border-white/10 bg-slate-950/65 p-6 shadow-[0_24px_90px_rgba(2,6,23,0.45)] backdrop-blur-xl">
      <div className="mb-6 space-y-2">
        <p className="text-[0.72rem] font-semibold uppercase tracking-[0.34em] text-cyan-200/70">
          Run Composer
        </p>
        <h2 className="text-2xl font-semibold tracking-[-0.03em] text-white">
          Launch the next dataset cycle.
        </h2>
        <p className="text-sm leading-6 text-slate-300/80">
          Prompt the run, declare the target classes, and choose how source material should resolve.
        </p>
      </div>

      <form className="space-y-5" onSubmit={onSubmit}>
        <label className="block space-y-2">
          <span className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-300/70">
            Prompt
          </span>
          <textarea
            value={prompt}
            onChange={(event) => onPromptChange(event.target.value)}
            placeholder="forklift in a warehouse with mixed lighting and side-angle views"
            rows={5}
            className="w-full rounded-[1.4rem] border border-white/10 bg-slate-900/70 px-4 py-3 text-sm leading-6 text-white outline-none transition focus:border-cyan-300/40 focus:bg-slate-900"
          />
        </label>

        <label className="block space-y-2">
          <span className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-300/70">
            Classes
          </span>
          <textarea
            value={classesValue}
            onChange={(event) => onClassesChange(event.target.value)}
            placeholder="forklift, pallet jack, safety helmet"
            rows={4}
            className="w-full rounded-[1.4rem] border border-white/10 bg-slate-900/70 px-4 py-3 text-sm leading-6 text-white outline-none transition focus:border-cyan-300/40 focus:bg-slate-900"
          />
          <p className="text-xs leading-5 text-slate-400">
            Separate classes with commas or new lines. Keep the first pass focused.
          </p>
        </label>

        <div className="space-y-2">
          <span className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-300/70">
            Source Mode
          </span>
          <div className="grid gap-3 sm:grid-cols-2">
            {([
              {
                value: "manifest",
                label: "Manifest",
                blurb: "Use a prebuilt source manifest for controlled, inspectable runs.",
              },
              {
                value: "live",
                label: "Live Search",
                blurb: "Resolve sources on demand through the search and downloader path.",
              },
            ] as const).map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => onSourceModeChange(option.value)}
                className={cn(
                  "rounded-[1.4rem] border px-4 py-4 text-left transition",
                  sourceMode === option.value
                    ? "border-cyan-300/40 bg-cyan-400/12 text-white"
                    : "border-white/10 bg-slate-900/55 text-slate-300 hover:border-white/20 hover:bg-slate-900/80",
                )}
              >
                <div className="mb-1 text-sm font-semibold">{option.label}</div>
                <p className="text-xs leading-5 text-inherit/75">{option.blurb}</p>
              </button>
            ))}
          </div>
        </div>

        {error ? (
          <div className="rounded-[1.2rem] border border-rose-400/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
            {error}
          </div>
        ) : null}

        <button
          type="submit"
          disabled={submitting}
          className={cn(
            "inline-flex w-full items-center justify-center rounded-full px-5 py-3 text-sm font-semibold uppercase tracking-[0.24em] transition",
            submitting
              ? "cursor-wait border border-white/10 bg-white/10 text-slate-200"
              : "border border-cyan-300/30 bg-gradient-to-r from-cyan-500 to-sky-500 text-white shadow-[0_18px_60px_rgba(14,165,233,0.28)] hover:brightness-110",
          )}
        >
          {submitting ? "Queueing Run" : "Launch Run"}
        </button>
      </form>
    </section>
  )
}
