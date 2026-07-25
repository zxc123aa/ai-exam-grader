import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"

import { ExamsService } from "@/client"
import { ImportCenterTabs } from "@/components/Exams/ImportCenterDialog"
import { Skeleton } from "@/components/ui/skeleton"

export const Route = createFileRoute("/_layout/exams_/$examId/")({
  component: ExamImportPage,
  head: () => ({ meta: [{ title: "导入试卷 - 点凡阅卷" }] }),
})

/**
 * 导入页：侧栏「导入试卷」的落点，整页内联渲染导入中心
 * （模板卷 / 学生答卷 / 标准答案文档），不再是弹窗。
 */
function ExamImportPage() {
  const { examId } = Route.useParams()
  const exam = useQuery({
    queryKey: ["exam", examId],
    queryFn: () => ExamsService.readExam({ examId }),
  })

  if (!exam.data) {
    return <Skeleton className="h-40 w-full rounded-2xl" />
  }

  return (
    <div className="rounded-2xl bg-card p-6 shadow-card">
      <ImportCenterTabs exam={exam.data} />
    </div>
  )
}
