import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { FileText } from "lucide-react"

import { ExamsService } from "@/client"
import { EmptyState } from "@/components/Common/EmptyState"
import ExamFilesDialog from "@/components/Exams/ExamFilesDialog"
import RegionMarkingCanvas from "@/components/Exams/RegionMarkingCanvas"

export const Route = createFileRoute("/_layout/exams_/$examId/marking")({
  component: ExamMarking,
  head: () => ({
    meta: [
      {
        title: "框选题目 - 点凡阅卷",
      },
    ],
  }),
})

function ExamMarking() {
  const { examId } = Route.useParams()
  const examQuery = useQuery({
    queryKey: ["exam", examId],
    queryFn: () => ExamsService.readExam({ examId }),
  })
  const filesQuery = useQuery({
    queryKey: ["exam-files", examId],
    queryFn: () => ExamsService.readExamFiles({ examId }),
  })
  const regionsQuery = useQuery({
    queryKey: ["exam-regions", examId],
    queryFn: () => ExamsService.readExamRegions({ examId }),
  })

  const documents = (filesQuery.data?.data ?? []).filter(
    (item) => item.document_type === "blank_exam",
  )
  const documentIds = new Set(documents.map((document) => document.id))
  const regions = (regionsQuery.data?.data ?? []).filter(
    (region) =>
      (region.exam_document_id && documentIds.has(region.exam_document_id)) ||
      (!region.exam_document_id && documents.length === 1),
  )

  return (
    <div className="grid gap-4">
      {filesQuery.isLoading || regionsQuery.isLoading ? (
        <div className="rounded-2xl border bg-card p-8 text-muted-foreground text-sm shadow-card">
          正在加载区域标注工作区
        </div>
      ) : documents.length === 0 ? (
        <div className="grid gap-4">
          <EmptyState
            icon={FileText}
            title="还没有导入试卷"
            description="请先导入这套卷子的图片或 PDF，上传后可以在本页复核区域和页面校正结果"
            className="bg-card shadow-card"
          />
          {examQuery.data && (
            <div className="flex justify-center">
              <ExamFilesDialog exam={examQuery.data} />
            </div>
          )}
        </div>
      ) : (
        <RegionMarkingCanvas
          examId={examId}
          exam={examQuery.data}
          documents={documents}
          regions={regions}
        />
      )}
    </div>
  )
}
