import { useQuery } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  Outlet,
  useRouterState,
} from "@tanstack/react-router"
import { ArrowLeft } from "lucide-react"

import { ExamsService } from "@/client"
import { ExamWorkspaceNav } from "@/components/Exams/ExamWorkspaceNav"
import { Button } from "@/components/ui/button"

export const Route = createFileRoute("/_layout/exams_/$examId")({
  component: ExamWorkspaceLayout,
})

function ExamWorkspaceLayout() {
  const { examId } = Route.useParams()
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  })
  const exam = useQuery({
    queryKey: ["exam", examId],
    queryFn: () => ExamsService.readExam({ examId }),
  })

  // 答卷复核页保持原有布局，不叠加工作区步骤导航
  if (pathname.includes("/submissions/")) {
    return <Outlet />
  }

  return (
    <div className="grid gap-6">
      <header className="grid gap-4">
        <div>
          <Button variant="ghost" size="sm" asChild className="-ml-3 mb-2">
            <Link to="/exams">
              <ArrowLeft />
              考试管理
            </Link>
          </Button>
          <h1 className="text-2xl font-bold tracking-tight">
            {exam.data?.title ?? "考试工作区"}
          </h1>
        </div>
        <ExamWorkspaceNav examId={examId} />
      </header>
      <Outlet />
    </div>
  )
}
