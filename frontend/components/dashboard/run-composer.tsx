"use client"

import type { FormEvent, KeyboardEvent } from "react"
import { Plus, X } from "lucide-react"

import type { SourceMode } from "@/lib/dashboard-api"
import { cn } from "@/lib/utils"

interface RunComposerProps {
  prompt: string
  classes: string[]
  sourceMode: SourceMode
  submitting: boolean
  error: string | null
  onPromptChange: (value: string) => void
  onClassChange: (index: number, value: string) => void
  onAddClass: () => void
  onRemoveClass: (index: number) => void
  onSourceModeChange: (value: SourceMode) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
}

export function RunComposer({
  prompt,
  classes,
  sourceMode,
  submitting,
  error,
  onPromptChange,
  onClassChange,
  onAddClass,
  onRemoveClass,
  onSourceModeChange,
  onSubmit,
}: RunComposerProps) {
  function handleClassKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter" && event.key !== ",") {
      return
    }

    event.preventDefault()
    onAddClass()
  }

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

        <div className="space-y-2">
          <span className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-300/70">
            Classes
          </span>
          <div className="flex flex-wrap gap-3">
            {classes.map((className, index) => (
              <div
                key={`class-${index}`}
                className="flex min-w-[220px] flex-1 items-center gap-3 rounded-[1.35rem] border border-white/10 bg-slate-900/70 px-3 py-3 transition focus-within:border-cyan-300/40 focus-within:bg-slate-900"
              >
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-cyan-300/20 bg-cyan-400/10 text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-cyan-100">
                  {index + 1}
                </div>
                <input
                  value={className}
                  onChange={(event) => onClassChange(index, event.target.value)}
                  onKeyDown={handleClassKeyDown}
                  placeholder={`Class ${index + 1}`}
                  className="min-w-0 flex-1 bg-transparent text-sm leading-6 text-white outline-none placeholder:text-slate-500"
                />
                <button
                  type="button"
                  onClick={() => onRemoveClass(index)}
                  disabled={classes.length === 1}
                  className={cn(
                    "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border transition",
                    classes.length === 1
                      ? "cursor-not-allowed border-white/8 text-slate-600"
                      : "border-white/10 text-slate-300 hover:border-rose-300/30 hover:bg-rose-400/10 hover:text-rose-100",
                  )}
                  aria-label={`Remove class ${index + 1}`}
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            ))}

            <button
              type="button"
              onClick={onAddClass}
              className="inline-flex min-h-[72px] min-w-[180px] flex-1 items-center justify-center gap-2 rounded-[1.35rem] border border-dashed border-cyan-300/28 bg-cyan-400/8 px-4 py-3 text-sm font-semibold text-cyan-100 transition hover:border-cyan-200/40 hover:bg-cyan-400/14"
            >
              <Plus className="h-4 w-4" />
              Add class
            </button>
          </div>
          <p className="text-xs leading-5 text-slate-400">
            Each class gets its own field. Click `+` to add another target.
          </p>
        </div>

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
