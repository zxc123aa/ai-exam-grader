import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowLeft, FileText } from "lucide-react"

import { ExamsService } from "@/client"
import RegionMarkingCanvas from "@/components/Exams/RegionMarkingCanvas"
import { Button } from "@/components/ui/button"

export const Route = createFileRoute("/_layout/exams_/$examId/marking")({
  component: ExamMarking,
  head: () => ({
    meta: [
      {
        title: "Mark Exam - AI Exam Grader",
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

  const document = filesQuery.data?.data.find(
    (item) => item.document_type === "blank_exam",
  )
  const regions = regionsQuery.data?.data ?? []

  return (
    <div className="grid gap-6">
      <div>
        <Button variant="ghost" size="sm" asChild className="-ml-3 mb-2">
          <Link to="/exams">
            <ArrowLeft />
            Exams
          </Link>
        </Button>
        <h1 className="text-2xl font-bold tracking-tight">
          {examQuery.data?.title ?? "Exam Marking"}
        </h1>
        <p className="text-muted-foreground">
          Draw normalized question regions on the blank paper.
        </p>
      </div>

      {filesQuery.isLoading || regionsQuery.isLoading ? (
        <div className="rounded-md border p-8 text-sm text-muted-foreground">
          Loading marking workspace
        </div>
      ) : !document ? (
        <div className="rounded-md border p-8 text-sm text-muted-foreground">
          <FileText className="mb-3 size-6" />
          Upload a blank exam file before marking regions.
        </div>
      ) : (
        <RegionMarkingCanvas
          examId={examId}
          document={document}
          regions={regions}
        />
      )}
    </div>
  )
}
