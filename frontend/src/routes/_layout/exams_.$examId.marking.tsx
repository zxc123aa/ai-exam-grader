import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { FileText } from "lucide-react"

import { ExamsService } from "@/client"
import ExamFilesDialog from "@/components/Exams/ExamFilesDialog"
import RegionMarkingCanvas from "@/components/Exams/RegionMarkingCanvas"

export const Route = createFileRoute("/_layout/exams_/$examId/marking")({
  component: ExamMarking,
  head: () => ({
    meta: [
      {
        title: "区域校正 - 智阅卷",
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
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-muted-foreground">
          多张图片或 PDF 按顺序组成一份完整试卷。
        </p>
        {examQuery.data && <ExamFilesDialog exam={examQuery.data} />}
      </div>

      {filesQuery.isLoading || regionsQuery.isLoading ? (
        <div className="rounded-md border p-8 text-sm text-muted-foreground">
          正在加载区域标注工作区
        </div>
      ) : documents.length === 0 ? (
        <div className="flex flex-col gap-4 rounded-md border p-8">
          <FileText className="size-6 text-muted-foreground" />
          <div>
            <h2 className="font-medium">还没有导入试卷</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              请先导入这套卷子的图片或
              PDF，上传后可以在本页复核区域和页面校正结果。
            </p>
          </div>
          {examQuery.data && <ExamFilesDialog exam={examQuery.data} />}
        </div>
      ) : (
        <RegionMarkingCanvas
          examId={examId}
          documents={documents}
          regions={regions}
        />
      )}
    </div>
  )
}
