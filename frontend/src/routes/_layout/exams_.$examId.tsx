import { useQuery } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  Outlet,
  useRouterState,
} from "@tanstack/react-router"
import { ArrowLeft, Upload } from "lucide-react"

import { ExamsService } from "@/client"
import { PageHead } from "@/components/Common/PageHead"
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

  // 批卷工作台 / 改卷报告 / 班级分析是顶层视图（侧栏直达），
  // 不叠加「导入 → 区域校正 → …」的步骤条——步骤条只属于试卷设置流程。
  const isTopLevelView = ["/workbench", "/report", "/scores"].some((suffix) =>
    pathname.endsWith(suffix),
  )

  return (
    <div className="grid gap-6">
      <header className="grid gap-4">
        <PageHead
          title={exam.data?.title ?? "考试工作区"}
          actions={
            <>
              <Button variant="ghost" size="sm" asChild>
                <Link to="/exams">
                  <ArrowLeft />
                  考试管理
                </Link>
              </Button>
              <Button variant="outline" size="sm" asChild>
                <Link to="/exams/$examId" params={{ examId }}>
                  <Upload />
                  导入试卷
                </Link>
              </Button>
            </>
          }
        />
        {!isTopLevelView && <ExamWorkspaceNav examId={examId} />}
      </header>
      <Outlet />
    </div>
  )
}
