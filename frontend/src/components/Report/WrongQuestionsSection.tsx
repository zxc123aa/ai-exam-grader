import { useQuery } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { Skeleton } from "@/components/ui/skeleton"
import { fetchSubmissionAnnotationCropBlob } from "@/lib/submission-media"
import { cn } from "@/lib/utils"
import {
  formatScore,
  type ReportQuestionItem,
  rateColor,
  scoreRate,
  sortQuestionsByLabel,
} from "./report-utils"

/** 单题答题裁切图；加载失败时静默隐藏（评语仍在）。 */
function AnnotationCrop({
  examId,
  submissionId,
  annotationId,
  label,
}: {
  examId: string
  submissionId: string
  annotationId: string
  label: string
}) {
  const [contentUrl, setContentUrl] = useState<string | null>(null)
  const { data, isPending, isError } = useQuery({
    queryKey: [
      "submission-annotation-crop",
      examId,
      submissionId,
      annotationId,
    ],
    queryFn: () =>
      fetchSubmissionAnnotationCropBlob(examId, submissionId, annotationId),
    staleTime: Number.POSITIVE_INFINITY,
  })

  useEffect(() => {
    if (!data) return
    const url = URL.createObjectURL(data)
    setContentUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [data])

  if (isError) return null
  if (isPending || !contentUrl) {
    return <Skeleton className="h-24 w-full max-w-md rounded-lg" />
  }
  return (
    <img
      src={contentUrl}
      alt={`${label} 答题裁切图`}
      className="max-h-44 w-auto max-w-full rounded-lg border bg-white object-contain"
    />
  )
}

/**
 * 错题区：得分率低于 60% 的题逐题展示题号、得分、答题裁切图（有权限时）
 * 与评语/正确思路。没有错题时整块不渲染。
 */
export function WrongQuestionsSection({
  examId,
  questions,
  knowledgeByLabel,
}: {
  examId: string
  questions: ReportQuestionItem[]
  knowledgeByLabel?: Map<string, string>
}) {
  const wrong = sortQuestionsByLabel(questions).filter((question) => {
    const rate = scoreRate(question)
    return rate != null && rate < 60
  })
  if (wrong.length === 0) return null

  return (
    <section className="border-t py-6">
      <div className="mb-4 flex items-baseline gap-2">
        <h4 className="font-semibold text-sm">错题回顾</h4>
        <span className="text-muted-foreground text-xs">
          得分率低于 60% 的 {wrong.length} 题
        </span>
      </div>
      <div className="flex flex-col gap-3">
        {wrong.map((question) => {
          const rate = scoreRate(question)
          const knowledgePoint = knowledgeByLabel?.get(question.label)
          return (
            <div key={question.label} className="rounded-lg border p-4">
              <div className="flex items-baseline gap-2 text-sm">
                <span className="font-medium">{question.label}</span>
                <span className={cn("font-semibold", rateColor(rate))}>
                  {formatScore(question.score)}
                </span>
                <span className="text-muted-foreground">
                  / {formatScore(question.maxScore)} 分
                </span>
                {knowledgePoint && (
                  <span className="ml-auto text-muted-foreground text-xs">
                    {knowledgePoint}
                  </span>
                )}
              </div>
              {question.submissionId && question.annotationId && (
                <div className="mt-3">
                  <AnnotationCrop
                    examId={examId}
                    submissionId={question.submissionId}
                    annotationId={question.annotationId}
                    label={question.label}
                  />
                </div>
              )}
              {question.comment && (
                <p className="mt-3 text-muted-foreground text-sm leading-6">
                  {question.comment}
                </p>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
