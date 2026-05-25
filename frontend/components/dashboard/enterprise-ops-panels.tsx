"use client"

import { Activity, AlertTriangle, GitCompare, History, Scale, ShieldCheck } from "lucide-react"
import type { ReactNode } from "react"

import enterpriseSpec from "@/specs/enterprise-ux.json"
import type { RunResource } from "@/lib/dashboard-api"
import { cn } from "@/lib/utils"

export function EnterpriseOpsPanels({ run }: { run: RunResource | null }) {
  const monitoring = run?.monitoring_summary ?? run?.summary?.monitoring_summary
  const resilience = run?.orchestration_resilience ?? run?.summary?.orchestration_resilience
  const summary = run?.summary

  return (
    <section className="rounded-lg border border-white/10 bg-slate-950/65 p-5 shadow-[0_20px_70px_rgba(2,6,23,0.38)] backdrop-blur-xl">
      <div className="mb-5 flex items-center justify-between gap-3">
        <div>
          <p className="text-[0.68rem] font-semibold uppercase tracking-[0.24em] text-cyan-200/70">Enterprise Ops</p>
          <h3 className="mt-2 text-lg font-semibold text-white">Operations, health, governance, and policy state.</h3>
        </div>
        <span className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[0.62rem] font-semibold uppercase tracking-[0.18em] text-slate-300">
          Phase 1
        </span>
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <SignalCard
          icon={<Activity className="h-4 w-4" />}
          label="Monitoring"
          value={monitoring?.alerts?.status ?? "pending"}
          meta={`${monitoring?.prometheus?.metric_count ?? 0} metrics / ${monitoring?.loki?.log_count ?? 0} logs`}
          tone={monitoring?.alerts?.status === "triggered" ? "warn" : "ok"}
        />
        <SignalCard
          icon={<History className="h-4 w-4" />}
          label="Resilience"
          value={resilience?.sla?.overall_state ?? "pending"}
          meta={`${resilience?.retry?.checkpoint_count ?? 0} checkpoints`}
          tone={resilience?.sla?.overall_state === "breached" || resilience?.sla?.overall_state === "escalated" ? "warn" : "ok"}
        />
        <SignalCard
          icon={<ShieldCheck className="h-4 w-4" />}
          label="Governance"
          value={String(summary?.license_compliance?.export_status ?? "pending")}
          meta={`${summary?.lineage_summary?.lineage_edges ?? 0} lineage edges`}
          tone={summary?.license_compliance?.export_status === "blocked" ? "warn" : "ok"}
        />
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <SpecPanel
          icon={<AlertTriangle className="h-4 w-4" />}
          title="Stage Diagnostics"
          items={enterpriseSpec.operations_dashboard.stage_diagnostics}
          statusItems={[
            `queue ${resilience?.concurrency?.backpressure_state ?? "unknown"}`,
            `dead-letter ${resilience?.dead_letter?.status ?? "empty"}`,
            `rollback ${resilience?.rollback?.status ?? "not_required"}`,
          ]}
        />
        <SpecPanel
          icon={<GitCompare className="h-4 w-4" />}
          title="Class Health"
          items={enterpriseSpec.class_health_regression_views.panels}
          statusItems={[
            `classes ${Object.keys(summary?.per_class_counts ?? {}).length}`,
            `gate ${String(summary?.promotion_guard_summary?.status ?? "not_evaluated")}`,
          ]}
        />
        <SpecPanel
          icon={<Scale className="h-4 w-4" />}
          title="Review And Governance"
          items={[...enterpriseSpec.label_qa_review_workflow.surfaces, ...enterpriseSpec.governance_visibility.surfaces]}
          statusItems={[
            `review ${summary?.review_queue_summary?.pending ?? 0} pending`,
            `license ${String(summary?.license_compliance?.summary?.blocked ?? 0)} blocked`,
          ]}
        />
        <SpecPanel
          icon={<ShieldCheck className="h-4 w-4" />}
          title="RBAC And Delivery"
          items={Object.keys(enterpriseSpec.rbac_matrix).map((role) => `${role}: ${enterpriseSpec.rbac_matrix[role as keyof typeof enterpriseSpec.rbac_matrix].actions.length} actions`)}
          statusItems={enterpriseSpec.phased_delivery.map((phase) => `P${phase.phase} ${phase.name}`)}
        />
      </div>
    </section>
  )
}

function SignalCard({
  icon,
  label,
  value,
  meta,
  tone,
}: {
  icon: ReactNode
  label: string
  value: string
  meta: string
  tone: "ok" | "warn"
}) {
  return (
    <div className={cn("rounded-lg border px-4 py-3", tone === "ok" ? "border-emerald-400/15 bg-emerald-500/8" : "border-amber-300/20 bg-amber-400/10")}>
      <div className="flex items-center gap-2 text-[0.65rem] font-semibold uppercase tracking-[0.2em] text-slate-300">
        {icon}
        {label}
      </div>
      <div className="mt-2 text-lg font-semibold text-white">{value}</div>
      <div className="mt-1 text-xs text-slate-400">{meta}</div>
    </div>
  )
}

function SpecPanel({
  icon,
  title,
  items,
  statusItems,
}: {
  icon: ReactNode
  title: string
  items: string[]
  statusItems: string[]
}) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/5 p-4">
      <div className="flex items-center gap-2 text-sm font-semibold text-white">
        {icon}
        {title}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {statusItems.map((item) => (
          <span key={item} className="rounded-md border border-white/10 bg-slate-950/50 px-2 py-1 text-xs text-slate-300">
            {item}
          </span>
        ))}
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {items.slice(0, 6).map((item) => (
          <div key={item} className="truncate rounded-md border border-white/8 bg-slate-950/40 px-2 py-2 text-xs text-slate-400">
            {item.replaceAll("_", " ")}
          </div>
        ))}
      </div>
    </div>
  )
}
