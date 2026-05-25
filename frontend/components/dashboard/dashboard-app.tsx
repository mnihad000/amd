"use client"

import {
  useCallback,
  type FormEvent,
  useEffect,
  useRef,
  useState,
  useTransition,
} from "react"
import { useRouter, useSearchParams } from "next/navigation"

import { ArtifactPanels } from "@/components/dashboard/artifact-panels"
import { EnterpriseOpsPanels } from "@/components/dashboard/enterprise-ops-panels"
import { formatDateTime, statusTone } from "@/components/dashboard/format"
import { RecentRunsList } from "@/components/dashboard/recent-runs-list"
import { RunComposer } from "@/components/dashboard/run-composer"
import { RunStatusHeader } from "@/components/dashboard/run-status-header"
import { StageTimeline } from "@/components/dashboard/stage-timeline"
import type { ArtifactDataBundle, ClassPlanEntry, EvaluationReport, FrameScoreRecord, SampleRecord } from "@/components/dashboard/types"
import {
  cancelRun,
  createRun,
  getArtifactJson,
  getArtifacts,
  getHealth,
  getRun,
  listRuns,
  type HealthResponse,
  type RunResource,
  type SourceMode,
} from "@/lib/dashboard-api"
import { cn } from "@/lib/utils"

const DEFAULT_PROMPT = "forklift in a warehouse"
const DEFAULT_CLASSES = ["forklift"]

export function DashboardApp() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const selectedJobId = searchParams.get("run")
  const workspaceRef = useRef<HTMLElement | null>(null)
  const [isRoutingPending, startRoutingTransition] = useTransition()

  const [prompt, setPrompt] = useState(DEFAULT_PROMPT)
  const [classes, setClasses] = useState<string[]>(DEFAULT_CLASSES)
  const [sourceMode, setSourceMode] = useState<SourceMode>("manifest")
  const [activeRun, setActiveRun] = useState<RunResource | null>(null)
  const [recentRuns, setRecentRuns] = useState<RunResource[]>([])
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [artifactData, setArtifactData] = useState<ArtifactDataBundle | null>(null)
  const [composerError, setComposerError] = useState<string | null>(null)
  const [artifactError, setArtifactError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const activeRunJobId = activeRun?.job_id
  const activeRunStatus = activeRun?.status

  const focusWorkspace = useCallback(() => {
    workspaceRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })
  }, [])

  const updateSelectedRun = useCallback((jobId: string) => {
    startRoutingTransition(() => {
      router.replace(`/app?run=${encodeURIComponent(jobId)}`, { scroll: false })
    })
    focusWorkspace()
  }, [focusWorkspace, router, startRoutingTransition])

  const loadOverview = useCallback(async (selectLatest: boolean) => {
    try {
      const [runsResponse, healthResponse] = await Promise.all([listRuns(10), getHealth()])
      setRecentRuns(runsResponse.runs)
      setHealth(healthResponse)

      if (selectLatest && !selectedJobId && runsResponse.runs[0]) {
        setActiveRun(runsResponse.runs[0])
        updateSelectedRun(runsResponse.runs[0].job_id)
      }
    } catch {
      // Keep the dashboard usable even if the overview refresh fails transiently.
    }
  }, [selectedJobId, updateSelectedRun])

  const loadActiveRun = useCallback(async (jobId: string) => {
    try {
      const run = await getRun(jobId)
      setActiveRun(run)
      if (run.status !== "completed") {
        setArtifactData(null)
        setArtifactError(null)
      }
    } catch (error) {
      setComposerError(error instanceof Error ? error.message : "Failed to load the selected run.")
    }
  }, [])

  const loadArtifactData = useCallback(async (jobId: string) => {
    try {
      const artifacts = await getArtifacts(jobId)
      const fetchArtifact = async <T,>(artifactName: string, fallback: T): Promise<T> => {
        try {
          return await getArtifactJson<T>(jobId, artifactName)
        } catch {
          return fallback
        }
      }

      const [classPlan, evaluationReport, acceptedFrames, frameScores, sampleManifest] = await Promise.all([
        fetchArtifact<ClassPlanEntry[]>("class_plan", []),
        fetchArtifact<EvaluationReport | null>("evaluation_report", null),
        fetchArtifact<SampleRecord[]>("accepted_frames", []),
        fetchArtifact<FrameScoreRecord[]>("frame_scores", []),
        fetchArtifact<SampleRecord[]>("sample_manifest", []),
      ])

      setArtifactData({
        artifacts,
        classPlan,
        evaluationReport,
        acceptedFrames,
        frameScores,
        sampleManifest,
      })
      setArtifactError(null)
    } catch (error) {
      setArtifactData(null)
      setArtifactError(error instanceof Error ? error.message : "Failed to load run artifacts.")
    }
  }, [])

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      void loadOverview(true)
    }, 0)

    return () => window.clearTimeout(timeoutId)
  }, [loadOverview])

  useEffect(() => {
    if (!selectedJobId) {
      return
    }

    const timeoutId = window.setTimeout(() => {
      setComposerError(null)
      setArtifactError(null)
      setArtifactData(null)
      void loadActiveRun(selectedJobId)
    }, 0)

    return () => window.clearTimeout(timeoutId)
  }, [loadActiveRun, selectedJobId])

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      void loadOverview(false)
    }, 6000)

    return () => window.clearInterval(intervalId)
  }, [loadOverview])

  useEffect(() => {
    if (!selectedJobId || !activeRunStatus) {
      return
    }

    if (activeRunStatus !== "queued" && activeRunStatus !== "running") {
      return
    }

    const intervalId = window.setInterval(() => {
      void loadActiveRun(selectedJobId)
    }, 2000)

    return () => window.clearInterval(intervalId)
  }, [activeRunStatus, loadActiveRun, selectedJobId])

  useEffect(() => {
    if (!activeRunJobId || activeRunStatus !== "completed") {
      return
    }

    const timeoutId = window.setTimeout(() => {
      void loadArtifactData(activeRunJobId)
    }, 0)

    return () => window.clearTimeout(timeoutId)
  }, [activeRunJobId, activeRunStatus, loadArtifactData])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const normalizedClasses = classes.map((item) => item.trim()).filter(Boolean)

    if (!prompt.trim() || !normalizedClasses.length) {
      setComposerError("A prompt and at least one class are required.")
      return
    }

    setSubmitting(true)
    setComposerError(null)
    setArtifactError(null)

    try {
      const run = await createRun({
        prompt: prompt.trim(),
        classes: normalizedClasses,
        source_mode: sourceMode,
      })
      setActiveRun(run)
      setArtifactData(null)
      updateSelectedRun(run.job_id)
      await loadOverview(false)
    } catch (error) {
      setComposerError(error instanceof Error ? error.message : "Failed to create the run.")
    } finally {
      setSubmitting(false)
    }
  }

  async function handleCancel() {
    if (!activeRun) {
      return
    }

    setCancelling(true)
    try {
      const run = await cancelRun(activeRun.job_id)
      setActiveRun(run)
      await loadOverview(false)
    } catch (error) {
      setComposerError(error instanceof Error ? error.message : "Failed to cancel the run.")
    } finally {
      setCancelling(false)
    }
  }

  return (
    <main className="relative min-h-screen overflow-hidden bg-[radial-gradient(circle_at_top_left,rgba(34,211,238,0.14),transparent_26%),radial-gradient(circle_at_80%_10%,rgba(59,130,246,0.18),transparent_24%),radial-gradient(circle_at_50%_120%,rgba(56,189,248,0.1),transparent_32%),linear-gradient(180deg,#020617_0%,#081121_46%,#020617_100%)] text-slate-100">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(148,163,184,0.05)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.05)_1px,transparent_1px)] bg-[size:48px_48px] opacity-30" />
      <div className="pointer-events-none absolute inset-x-0 top-0 h-64 bg-[radial-gradient(circle_at_top,rgba(14,165,233,0.25),transparent_60%)] blur-3xl" />

      <div className="relative mx-auto max-w-[1600px] px-4 py-6 sm:px-6 lg:px-8">
        <header className="overflow-hidden rounded-[2.2rem] border border-white/10 bg-slate-950/55 p-6 shadow-[0_30px_110px_rgba(2,6,23,0.48)] backdrop-blur-xl">
          <div className="flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
            <div className="max-w-3xl space-y-3">
              <p className="text-[0.72rem] font-semibold uppercase tracking-[0.36em] text-cyan-200/75">
                Operator Dashboard
              </p>
              <h1 className="text-4xl font-semibold tracking-[-0.05em] text-white sm:text-5xl">
                Async run control for dataset generation and YOLO evaluation.
              </h1>
              <p className="max-w-2xl text-sm leading-7 text-slate-300/80 sm:text-base">
                Queue runs from the browser, monitor stage progress, inspect artifacts, and reopen recent jobs
                without leaving the operator surface.
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-3 xl:min-w-[620px]">
              <HeaderStat
                label="Service"
                value={health?.status ?? "connecting"}
                accent={health ? statusTone(health.status === "ready" ? "completed" : "queued") : "border-white/10 bg-white/5 text-slate-200"}
              />
              <HeaderStat
                label="Workers"
                value={health ? String(health.active_worker_count) : "0"}
                meta={health ? `${health.queued_run_count} queued` : "Awaiting health"}
              />
              <HeaderStat
                label="Selected Run"
                value={selectedJobId ?? "latest"}
                meta={activeRun ? formatDateTime(activeRun.updated_at) : isRoutingPending ? "routing" : "idle"}
              />
            </div>
          </div>
        </header>

        <div className="mt-8 grid gap-6 xl:grid-cols-[minmax(320px,0.95fr)_minmax(0,1.55fr)_320px]">
          <div className="space-y-6">
            <RunComposer
              prompt={prompt}
              classes={classes}
              sourceMode={sourceMode}
              submitting={submitting}
              error={composerError}
              onPromptChange={setPrompt}
              onClassChange={(index, value) => {
                setClasses((current) => current.map((item, itemIndex) => (itemIndex === index ? value : item)))
              }}
              onAddClass={() => {
                setClasses((current) => [...current, ""])
              }}
              onRemoveClass={(index) => {
                setClasses((current) => {
                  if (current.length === 1) {
                    return current
                  }

                  return current.filter((_, itemIndex) => itemIndex !== index)
                })
              }}
              onSourceModeChange={setSourceMode}
              onSubmit={handleSubmit}
            />
          </div>

          <section ref={workspaceRef} className="space-y-6">
            <RunStatusHeader run={activeRun} cancelling={cancelling} onCancel={handleCancel} />
            <StageTimeline run={activeRun} />
            <EnterpriseOpsPanels run={activeRun} />
            <ArtifactPanels run={activeRun} artifactData={artifactData} artifactError={artifactError} />
          </section>

          <div className="space-y-6">
            <RecentRunsList
              runs={recentRuns}
              activeJobId={selectedJobId}
              onSelect={updateSelectedRun}
            />
          </div>
        </div>
      </div>
    </main>
  )
}

function HeaderStat({
  label,
  value,
  meta,
  accent,
}: {
  label: string
  value: string
  meta?: string
  accent?: string
}) {
  return (
    <div className={cn("rounded-[1.4rem] border border-white/10 bg-white/5 px-4 py-4", accent)}>
      <div className="text-[0.66rem] font-semibold uppercase tracking-[0.24em] text-slate-300/70">{label}</div>
      <div className="mt-2 truncate text-lg font-semibold text-white">{value}</div>
      {meta ? <div className="mt-1 text-xs uppercase tracking-[0.2em] text-slate-400">{meta}</div> : null}
    </div>
  )
}
