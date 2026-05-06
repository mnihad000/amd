import type { ArtifactsResponse, RunResource } from "@/lib/dashboard-api"

export interface ClassPlanEntry {
  name: string
  final_state: string
  feasibility_score: number
  reasons: string[]
  discovered_sources: number
  accepted_samples: number
  avg_label_confidence: number | null
}

export interface EvaluationReport {
  status: string
  map50: number | null
  precision: number | null
  recall: number | null
  weak_classes: string[]
  class_outcomes: Record<string, string>
  notes: string[]
}

export interface SampleRecord {
  id: string
  path: string
  class_names: string[]
  source_type: string
  quality_score?: number | null
}

export interface FrameScoreRecord {
  sample_id: string
  quality_score: number
  decision: string
  rejection_reasons: string[]
}

export interface PreviewSample {
  id: string
  title: string
  imageUrl: string | null
  meta: string
  note?: string
}

export interface ArtifactDataBundle {
  artifacts: ArtifactsResponse | null
  classPlan: ClassPlanEntry[]
  evaluationReport: EvaluationReport | null
  acceptedFrames: SampleRecord[]
  frameScores: FrameScoreRecord[]
  sampleManifest: SampleRecord[]
}

export interface DashboardState {
  activeRun: RunResource | null
  artifactData: ArtifactDataBundle | null
  artifactError: string | null
}
