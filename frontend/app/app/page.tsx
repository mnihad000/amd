import { DashboardApp } from "@/components/dashboard/dashboard-app"
import { Suspense } from "react"

export default function AppPage() {
  return (
    <Suspense fallback={null}>
      <DashboardApp />
    </Suspense>
  )
}
