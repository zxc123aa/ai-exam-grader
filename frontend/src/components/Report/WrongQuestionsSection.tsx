import { useQuery } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { Skeleton } from "@/components/ui/skeleton"
import {
  fetchSubmissionAnnotationCropBlob,
  fetchWrongbookEntryImageBlob,
} from "@/lib/submission-media"
import { cn } from "@/lib/utils"
import {
  formatScore,
  type ReportQuestionItem,
  rateColor,
  scoreRate,
  sortQuestionsByLabel,
} from "./report-utils"

/**
 * 单题答题图；加载失败时静默隐藏（评语仍在）。
 *
 * 两个来源：教师侧按题区实时裁切，学生侧取错题本条目留存的图。学生没有考试接口
 * 权限，只能走后者。
 */
function AnswerImage({
  examId,
  submissionId,
  annotationId,
  entryId,
  label,
}: {
  examId: string
  submissionId?: string | null
  annotationId?: string | null
  entryId?: string | null
  label: string
}) {
  const [contentUrl, setContentUrl] = useState<string | null>(null)
  const { data, isPending, isError } = useQuery({
    queryKey: entryId
      ? ["wrongbook-entry-image", entryId]
      : ["submission-annotation-crop", examId, submissionId, annotationId],
    queryFn: () =>
      entryId
        ? fetchWrongbookEntryImageBlob(entryId)
        : fetchSubmissionAnnotationCropBlob(
            examId,
            submissionId as string,
            annotationId as string,
          ),
    staleTime: Number.POSITIVE_INFINITY,
  })

  useEffect(() => {
    if (!data) return
    const url = URL.createObjectURL(data)
    setContentUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [data])

  if (isError) {
    return (
      <div className="flex h-24 w-full max-w-md items-center justify-center rounded-lg border border-dashed text-muted-foreground text-xs">
        答题图暂不可用
      </div>
    )
  }
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
              {((question.entryId && question.hasImage) ||
                (question.submissionId && question.annotationId)) && (
                <div className="mt-3">
                  <AnswerImage
                    examId={examId}
                    submissionId={question.submissionId}
                    annotationId={question.annotationId}
                    entryId={question.hasImage ? question.entryId : null}
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
