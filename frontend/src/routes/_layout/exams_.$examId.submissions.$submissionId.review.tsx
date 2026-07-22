import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ArrowLeft,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Loader2,
  MessageSquareText,
} from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import {
  ApiError,
  type ExamRegionPublic,
  ExamsService,
  OpenAPI,
  type ProcessingTaskPublic,
  type StandardAnswerPublic,
  type StudentSubmissionPublic,
  type SubmissionAnnotationPublic,
  type SubmissionAnnotationStatus,
  TasksService,
} from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
import { cn } from "@/lib/utils"
import { handleError } from "@/utils"

export const Route = createFileRoute(
  "/_layout/exams_/$examId/submissions/$submissionId/review",
)({
  component: SubmissionReview,
  head: () => ({
    meta: [
      {
        title: "答卷复核 - 智阅卷",
      },
    ],
  }),
})

type AnnotationForm = {
  score: string
  maxScore: string
  comment: string
  status: SubmissionAnnotationStatus
}

async function fetchSubmissionPageImageBlob(
  examId: string,
  submissionId: string,
  pageNumber: number,
) {
  const token = localStorage.getItem("access_token")
  const base = OpenAPI.BASE || ""
  const response = await fetch(
    `${base}/api/v1/exams/${examId}/submissions/${submissionId}/pages/${pageNumber}/image`,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    },
  )
  if (!response.ok) {
    throw new ApiError(
      {
        method: "GET",
        url: "/api/v1/exams/{exam_id}/submissions/{submission_id}/pages/{page_number}/image",
      },
      {
        url: response.url,
        ok: response.ok,
        status: response.status,
        statusText: response.statusText,
        body: await response.text(),
      },
      "Failed to load student submission preview",
    )
  }
  return response.blob()
}

async function fetchSubmissionAnnotationCropBlob(
  examId: string,
  submissionId: string,
  annotationId: string,
) {
  const token = localStorage.getItem("access_token")
  const base = OpenAPI.BASE || ""
  const response = await fetch(
    `${base}/api/v1/exams/${examId}/submissions/${submissionId}/annotations/${annotationId}/crop`,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    },
  )
  if (!response.ok) {
    throw new ApiError(
      {
        method: "GET",
        url: "/api/v1/exams/{exam_id}/submissions/{submission_id}/annotations/{annotation_id}/crop",
      },
      {
        url: response.url,
        ok: response.ok,
        status: response.status,
        statusText: response.statusText,
        body: await response.text(),
      },
      "Failed to load annotation crop",
    )
  }
  return response.blob()
}

async function fetchSubmissionRegionCropBlob(
  examId: string,
  submissionId: string,
  regionId: string,
) {
  const token = localStorage.getItem("access_token")
  const base = OpenAPI.BASE || ""
  const response = await fetch(
    `${base}/api/v1/exams/${examId}/submissions/${submissionId}/regions/${regionId}/crop`,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    },
  )
  if (!response.ok) {
    throw new ApiError(
      {
        method: "GET",
        url: "/api/v1/exams/{exam_id}/submissions/{submission_id}/regions/{region_id}/crop",
      },
      {
        url: response.url,
        ok: response.ok,
        status: response.status,
        statusText: response.statusText,
        body: await response.text(),
      },
      "Failed to load region crop",
    )
  }
  return response.blob()
}

function formatStatus(status?: string | null) {
  const value = status || "needs_review"
  const labels: Record<string, string> = {
    needs_review: "待复核",
    accepted: "已通过",
    rejected: "已驳回",
    pending: "等待处理",
    queued: "排队中",
    running: "处理中",
    completed: "已完成",
    failed: "失败",
    registration_pending: "等待配准",
    manual_confirmed: "人工确认",
    auto_registered: "自动配准",
    auto_confirmed: "自动配准",
  }
  return labels[value] || value
}

function formatOcrStatus(status?: string | null) {
  const value = status || "not_started"
  const labels: Record<string, string> = {
    not_started: "未开始",
    queued: "排队中",
    running: "识别中",
    completed: "已完成",
    failed: "失败",
  }
  return labels[value] || value
}

function formatTaskProgress(task?: ProcessingTaskPublic | null) {
  if (!task) return "尚未开始处理"
  return `${formatStatus(task.status)} · ${task.progress ?? 0}%`
}

function toForm(annotation?: SubmissionAnnotationPublic): AnnotationForm {
  return {
    score: annotation?.score == null ? "" : String(annotation.score),
    maxScore: annotation?.max_score == null ? "" : String(annotation.max_score),
    comment: annotation?.comment ?? "",
    status: annotation?.status ?? "needs_review",
  }
}

function toOptionalNumber(value: string) {
  const trimmed = value.trim()
  if (!trimmed) return null
  const numeric = Number(trimmed)
  return Number.isFinite(numeric) ? numeric : null
}

function getRegionAnnotation(
  annotations: SubmissionAnnotationPublic[],
  regionId: string,
) {
  return annotations.find(
    (annotation) => annotation.exam_region_id === regionId,
  )
}

// 跨页续题：批注挂在正题（primary）区域上，续页区域共享同一题目的批注。
function getPrimaryRegion(
  regions: ExamRegionPublic[],
  region: ExamRegionPublic,
) {
  if (region.region_role !== "continuation" || !region.question_key) {
    return region
  }
  return (
    regions.find(
      (item) =>
        item.question_key === region.question_key &&
        item.region_role !== "continuation",
    ) ?? region
  )
}

function getEffectiveAnnotation(
  annotations: SubmissionAnnotationPublic[],
  regions: ExamRegionPublic[],
  region: ExamRegionPublic,
) {
  return getRegionAnnotation(annotations, getPrimaryRegion(regions, region).id)
}

function getRegionPageNumber(region: ExamRegionPublic) {
  return region.page_number ?? 1
}

function SubmissionPagePreview({
  examId,
  submission,
  regions,
  annotations,
  selectedRegionId,
  pageNumber,
  setPageNumber,
  onSelectRegion,
}: {
  examId: string
  submission: StudentSubmissionPublic
  regions: ExamRegionPublic[]
  annotations: SubmissionAnnotationPublic[]
  selectedRegionId: string | null
  pageNumber: number
  setPageNumber: (pageNumber: number) => void
  onSelectRegion: (regionId: string) => void
}) {
  const pageCount = submission.page_count ?? 1
  const [contentUrl, setContentUrl] = useState<string | null>(null)
  const { data, isLoading, isError } = useQuery({
    queryKey: [
      "review-submission-page-image",
      examId,
      submission.id,
      pageNumber,
    ],
    queryFn: () =>
      fetchSubmissionPageImageBlob(examId, submission.id, pageNumber),
  })

  useEffect(() => {
    if (!data) {
      setContentUrl(null)
      return
    }
    const url = URL.createObjectURL(data)
    setContentUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [data])

  const pageRegions = regions.filter(
    (region) => getRegionPageNumber(region) === pageNumber,
  )

  return (
    <div className="grid content-start gap-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm text-muted-foreground tabular-nums">
          第 {pageNumber} / {pageCount} 页
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={pageNumber <= 1}
            onClick={() => setPageNumber(Math.max(1, pageNumber - 1))}
          >
            <ChevronLeft />
            上一页
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={pageNumber >= pageCount}
            onClick={() => setPageNumber(Math.min(pageCount, pageNumber + 1))}
          >
            下一页
            <ChevronRight />
          </Button>
        </div>
      </div>
      {isError ? (
        <div className="rounded-md border p-8 text-sm text-destructive">
          无法加载答卷预览。
        </div>
      ) : isLoading || !contentUrl ? (
        <div className="flex items-center gap-2 rounded-md border p-8 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          正在加载复核预览
        </div>
      ) : (
        <div
          className="relative overflow-hidden rounded-md border bg-muted/20"
          data-testid="submission-review-canvas"
        >
          <img
            alt={submission.stored_file.original_filename}
            className="block w-full select-none"
            draggable={false}
            src={contentUrl}
          />
          {pageRegions.map((region) => {
            const annotation = getRegionAnnotation(annotations, region.id)
            const isSelected = selectedRegionId === region.id
            return (
              <button
                key={region.id}
                type="button"
                className={cn(
                  "absolute border-2 bg-sky-500/10 text-left outline-none transition-colors",
                  isSelected
                    ? "border-emerald-500 bg-emerald-500/15"
                    : "border-sky-500 hover:border-emerald-500",
                )}
                data-testid={`review-region-${region.label}`}
                onClick={() => onSelectRegion(region.id)}
                style={{
                  left: `${region.x * 100}%`,
                  top: `${region.y * 100}%`,
                  width: `${region.width * 100}%`,
                  height: `${region.height * 100}%`,
                }}
              >
                <span
                  className={cn(
                    "absolute left-1 top-1 rounded-sm px-1.5 py-0.5 text-xs font-medium text-white",
                    annotation ? "bg-emerald-600" : "bg-sky-600",
                  )}
                >
                  {region.label}
                </span>
              </button>
            )
          })}
        </div>
      )}
      {pageRegions.length === 0 && (
        <div className="text-xs text-muted-foreground">
          当前页面还没有模板题区。
        </div>
      )}
    </div>
  )
}

function AnnotationCropPreview({
  examId,
  submissionId,
  annotation,
}: {
  examId: string
  submissionId: string
  annotation?: SubmissionAnnotationPublic
}) {
  const [contentUrl, setContentUrl] = useState<string | null>(null)
  const { data, isLoading, isError } = useQuery({
    queryKey: [
      "submission-annotation-crop",
      examId,
      submissionId,
      annotation?.id,
    ],
    queryFn: () =>
      fetchSubmissionAnnotationCropBlob(
        examId,
        submissionId,
        annotation?.id as string,
      ),
    enabled: Boolean(annotation?.id),
  })

  useEffect(() => {
    if (!data) {
      setContentUrl(null)
      return
    }
    const url = URL.createObjectURL(data)
    setContentUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [data])

  if (!annotation) {
    return (
      <div className="rounded-md border p-3 text-xs text-muted-foreground">
        请先运行自动处理，生成所选区域的题目裁切图。
      </div>
    )
  }
  if (isError) {
    return (
      <div className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">
        题目裁切图暂不可用。
      </div>
    )
  }
  if (isLoading || !contentUrl) {
    return (
      <div className="flex items-center gap-2 rounded-md border p-3 text-xs text-muted-foreground">
        <Loader2 className="size-3 animate-spin" />
        正在加载题目裁切图
      </div>
    )
  }
  return (
    <div className="overflow-hidden rounded-md border bg-muted/20">
      <img
        alt={`${annotation.label} crop`}
        className="block w-full"
        data-testid="annotation-crop-preview"
        src={contentUrl}
      />
    </div>
  )
}

// 续页区域的裁切图：按区域坐标在学生答卷上裁切，用于查看跨页答案的续写部分。
function RegionCropPreview({
  examId,
  submissionId,
  region,
}: {
  examId: string
  submissionId: string
  region: ExamRegionPublic
}) {
  const [contentUrl, setContentUrl] = useState<string | null>(null)
  const { data, isLoading, isError } = useQuery({
    queryKey: ["submission-region-crop", examId, submissionId, region.id],
    queryFn: () =>
      fetchSubmissionRegionCropBlob(examId, submissionId, region.id),
  })

  useEffect(() => {
    if (!data) {
      setContentUrl(null)
      return
    }
    const url = URL.createObjectURL(data)
    setContentUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [data])

  if (isError) {
    return (
      <div className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">
        续页裁切图暂不可用。
      </div>
    )
  }
  if (isLoading || !contentUrl) {
    return (
      <div className="flex items-center gap-2 rounded-md border p-3 text-xs text-muted-foreground">
        <Loader2 className="size-3 animate-spin" />
        正在加载续页裁切图
      </div>
    )
  }
  return (
    <div className="grid gap-1">
      <div className="text-xs text-muted-foreground">
        续页裁切（第 {getRegionPageNumber(region)} 页，与正题同一评分）
      </div>
      <div className="overflow-hidden rounded-md border bg-muted/20">
        <img
          alt={`${region.label} crop`}
          className="block w-full"
          data-testid="region-crop-preview"
          src={contentUrl}
        />
      </div>
    </div>
  )
}

function AnnotationOcrDraft({
  annotation,
}: {
  annotation?: SubmissionAnnotationPublic
}) {
  if (!annotation) {
    return (
      <div className="rounded-md border p-3 text-xs text-muted-foreground">
        请先运行自动处理，生成 OCR 识别草稿。
      </div>
    )
  }

  const hasText = Boolean(annotation.ocr_text?.trim())
  return (
    <div className="grid gap-2 rounded-md border p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-medium">OCR 识别草稿</div>
        <Badge
          variant={hasText ? "secondary" : "outline"}
          className="capitalize"
          data-testid="annotation-ocr-status"
        >
          {formatOcrStatus(annotation.ocr_status)}
        </Badge>
      </div>
      {annotation.ocr_engine && (
        <div className="text-xs text-muted-foreground">
          识别引擎：{annotation.ocr_engine}
        </div>
      )}
      {hasText ? (
        <div
          className="max-h-36 overflow-auto whitespace-pre-wrap rounded-sm bg-muted/50 p-2 text-xs"
          data-testid="annotation-ocr-text"
        >
          {annotation.ocr_text}
        </div>
      ) : (
        <div className="text-xs text-muted-foreground">暂无 OCR 识别文本。</div>
      )}
    </div>
  )
}

function formatConfidence(value?: number | null) {
  if (value == null) return "n/a"
  return `${Math.round(value * 100)}%`
}

function StandardAnswerReference({
  answer,
}: {
  answer?: StandardAnswerPublic
}) {
  if (!answer) {
    return (
      <div
        className="rounded-md border p-3 text-xs text-muted-foreground"
        data-testid="review-standard-answer"
      >
        该区域还没有可用的标准答案。
      </div>
    )
  }

  return (
    <div
      className="grid gap-2 rounded-md border p-3"
      data-testid="review-standard-answer"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-medium">标准答案</div>
        <Badge variant={answer.status === "ready" ? "secondary" : "outline"}>
          {formatStatus(answer.status)}
        </Badge>
      </div>
      <div className="max-h-28 overflow-auto whitespace-pre-wrap rounded-sm bg-muted/50 p-2 text-xs">
        {answer.answer_text}
      </div>
      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
        <span>满分 {answer.max_score}</span>
        <span>{answer.scoring_points?.length ?? 0} 个评分点</span>
      </div>
      {answer.rubric_text && (
        <div className="whitespace-pre-wrap text-xs text-muted-foreground">
          {answer.rubric_text}
        </div>
      )}
    </div>
  )
}

function GradingDraft({
  annotation,
  onApplySuggestion,
}: {
  annotation?: SubmissionAnnotationPublic
  onApplySuggestion: () => void
}) {
  if (!annotation) {
    return (
      <div
        className="rounded-md border p-3 text-xs text-muted-foreground"
        data-testid="review-grading-draft"
      >
        请先运行自动处理，生成评分草稿。
      </div>
    )
  }

  const hasSuggestion = annotation.suggested_score != null
  return (
    <div
      className="grid gap-2 rounded-md border p-3"
      data-testid="review-grading-draft"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-medium">AI 评分草稿</div>
        <Badge
          variant={
            annotation.grading_status === "succeeded" ? "secondary" : "outline"
          }
        >
          {formatStatus(annotation.grading_status)}
        </Badge>
      </div>
      {hasSuggestion ? (
        <div className="grid gap-2">
          <div className="flex items-center justify-between gap-2 rounded-sm bg-muted/50 p-2 text-xs">
            <span>
              建议得分 {annotation.suggested_score}
              {annotation.max_score != null ? ` / ${annotation.max_score}` : ""}
            </span>
            <span className="text-muted-foreground">
              {formatConfidence(annotation.grading_confidence)}
            </span>
          </div>
          {annotation.suggested_comment && (
            <div className="whitespace-pre-wrap text-xs text-muted-foreground">
              {annotation.suggested_comment}
            </div>
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="review-apply-grading-suggestion-button"
            onClick={onApplySuggestion}
          >
            <CheckCircle2 />
            采纳建议
          </Button>
        </div>
      ) : (
        <div className="text-xs text-muted-foreground">暂无建议得分。</div>
      )}
    </div>
  )
}

function SubmissionReview() {
  const { examId, submissionId } = Route.useParams()
  const [pageNumber, setPageNumber] = useState(1)
  const [selectedRegionId, setSelectedRegionId] = useState<string | null>(null)
  const [processingTaskId, setProcessingTaskId] = useState<string | null>(null)
  const [form, setForm] = useState<AnnotationForm>(toForm())
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const examQuery = useQuery({
    queryKey: ["exam", examId],
    queryFn: () => ExamsService.readExam({ examId }),
  })
  const submissionQuery = useQuery({
    queryKey: ["student-submission", examId, submissionId],
    queryFn: () => ExamsService.readStudentSubmission({ examId, submissionId }),
  })
  const regionsQuery = useQuery({
    queryKey: ["student-submission-review-regions", examId, submissionId],
    queryFn: () =>
      ExamsService.readStudentSubmissionTemplateRegions({
        examId,
        submissionId,
      }),
  })
  const annotationsQuery = useQuery({
    queryKey: ["submission-annotations", examId, submissionId],
    queryFn: () =>
      ExamsService.readSubmissionAnnotations({ examId, submissionId }),
  })
  const standardAnswersQuery = useQuery({
    queryKey: ["standard-answers", examId],
    queryFn: () => ExamsService.readStandardAnswers({ examId }),
  })
  const processingTaskQuery = useQuery({
    queryKey: ["processing-task", processingTaskId],
    queryFn: () =>
      TasksService.readTask({ taskId: processingTaskId as string }),
    enabled: Boolean(processingTaskId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === "queued" || status === "running" ? 1000 : false
    },
  })

  const submission = submissionQuery.data
  const regions = useMemo(
    () => regionsQuery.data?.data ?? [],
    [regionsQuery.data?.data],
  )
  const annotations = useMemo(
    () => annotationsQuery.data?.data ?? [],
    [annotationsQuery.data?.data],
  )
  const standardAnswersByRegionId = useMemo(() => {
    return new Map(
      (standardAnswersQuery.data?.data ?? []).map((answer) => [
        answer.exam_region_id,
        answer,
      ]),
    )
  }, [standardAnswersQuery.data?.data])
  const selectedRegion = regions.find(
    (region) => region.id === selectedRegionId,
  )
  // 续页区域选中时，批注/标准答案/保存都落到正题（primary）区域上。
  const selectedPrimaryRegion = selectedRegion
    ? getPrimaryRegion(regions, selectedRegion)
    : undefined
  const selectedAnnotation = selectedRegion
    ? getEffectiveAnnotation(annotations, regions, selectedRegion)
    : undefined
  const selectedStandardAnswer = selectedPrimaryRegion
    ? standardAnswersByRegionId.get(selectedPrimaryRegion.id)
    : undefined

  useEffect(() => {
    if (!selectedRegionId && regions.length > 0) {
      setSelectedRegionId(regions[0].id)
      setPageNumber(getRegionPageNumber(regions[0]))
    }
  }, [regions, selectedRegionId])

  useEffect(() => {
    setForm(toForm(selectedAnnotation))
  }, [selectedAnnotation])

  const saveMutation = useMutation({
    mutationFn: () => {
      if (!selectedRegion || !selectedPrimaryRegion) {
        throw new Error("请先选择一个题目区域再保存")
      }
      const requestBody = {
        label: selectedPrimaryRegion.label,
        status: form.status,
        page_number: getRegionPageNumber(selectedPrimaryRegion),
        x: selectedPrimaryRegion.x,
        y: selectedPrimaryRegion.y,
        width: selectedPrimaryRegion.width,
        height: selectedPrimaryRegion.height,
        score: toOptionalNumber(form.score),
        max_score: toOptionalNumber(form.maxScore),
        comment: form.comment.trim() || null,
        exam_region_id: selectedPrimaryRegion.id,
      }
      if (selectedAnnotation) {
        return ExamsService.updateSubmissionAnnotation({
          examId,
          submissionId,
          annotationId: selectedAnnotation.id,
          requestBody,
        })
      }
      return ExamsService.createSubmissionAnnotation({
        examId,
        submissionId,
        requestBody,
      })
    },
    onSuccess: () => {
      showSuccessToast("批注已保存")
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["submission-annotations", examId, submissionId],
      })
    },
  })

  const processingMutation = useMutation({
    mutationFn: () =>
      ExamsService.createStudentSubmissionProcessingTask({
        examId,
        submissionId,
      }),
    onSuccess: (task) => {
      setProcessingTaskId(task.id)
      showSuccessToast("自动处理任务已开始")
      queryClient.invalidateQueries({
        queryKey: ["submission-annotations", examId, submissionId],
      })
      queryClient.invalidateQueries({
        queryKey: ["submission-annotation-crop", examId, submissionId],
      })
    },
    onError: handleError.bind(showErrorToast),
  })

  useEffect(() => {
    const status = processingTaskQuery.data?.status
    if (status === "succeeded") {
      queryClient.invalidateQueries({
        queryKey: ["submission-annotations", examId, submissionId],
      })
      queryClient.invalidateQueries({
        queryKey: ["submission-annotation-crop", examId, submissionId],
      })
    }
  }, [examId, processingTaskQuery.data?.status, queryClient, submissionId])

  const isLoading =
    examQuery.isLoading ||
    submissionQuery.isLoading ||
    regionsQuery.isLoading ||
    annotationsQuery.isLoading ||
    standardAnswersQuery.isLoading

  return (
    <div className="grid gap-6">
      <div>
        <Button variant="ghost" size="sm" asChild className="-ml-3 mb-2">
          <Link to="/exams">
            <ArrowLeft />
            考试管理
          </Link>
        </Button>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              {examQuery.data?.title ?? "答卷复核"}
            </h1>
            <p className="text-muted-foreground">
              {submission?.student_name || "未命名学生"} ·{" "}
              {submission?.student_identifier || "无学号"}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline" className="capitalize">
              {formatStatus(submission?.status ?? "registration_pending")}
            </Badge>
            <Badge variant="secondary" className="capitalize">
              {formatStatus(submission?.registration_status ?? "pending")}
            </Badge>
          </div>
        </div>
      </div>

      {isLoading || !submission ? (
        <div className="flex items-center gap-2 rounded-md border p-8 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          正在加载答卷复核工作区
        </div>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
          <SubmissionPagePreview
            examId={examId}
            submission={submission}
            regions={regions}
            annotations={annotations}
            selectedRegionId={selectedRegionId}
            pageNumber={pageNumber}
            setPageNumber={setPageNumber}
            onSelectRegion={(regionId) => {
              const region = regions.find((item) => item.id === regionId)
              setSelectedRegionId(regionId)
              if (region) setPageNumber(getRegionPageNumber(region))
            }}
          />

          <aside className="grid content-start gap-4">
            <div className="grid gap-3 rounded-md border p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-medium">自动处理流程</div>
                  <div className="text-xs text-muted-foreground">
                    {formatTaskProgress(
                      processingTaskQuery.data ?? processingMutation.data,
                    )}
                  </div>
                </div>
                {(processingMutation.isPending ||
                  processingTaskQuery.data?.status === "queued" ||
                  processingTaskQuery.data?.status === "running") && (
                  <Loader2 className="size-4 animate-spin text-muted-foreground" />
                )}
              </div>
              {processingTaskQuery.data?.error_message && (
                <div className="rounded-md border border-destructive/30 p-2 text-xs text-destructive">
                  {processingTaskQuery.data.error_message}
                </div>
              )}
              <LoadingButton
                data-testid="run-submission-processing-button"
                loading={processingMutation.isPending}
                onClick={() => processingMutation.mutate()}
              >
                开始自动处理
              </LoadingButton>
            </div>

            <div className="rounded-md border">
              <div className="flex items-center justify-between border-b px-4 py-3">
                <span className="text-sm font-medium">模板题目区域</span>
                <Badge variant="secondary">
                  {
                    regions.filter(
                      (region) => region.region_role !== "continuation",
                    ).length
                  }
                </Badge>
              </div>
              {regions.length === 0 ? (
                <div className="px-4 py-8 text-sm text-muted-foreground">
                  请先标注模板题目区域，再复核学生答卷。
                </div>
              ) : (
                <div className="divide-y">
                  {regions.map((region) => {
                    // 续页区域共享正题的批注状态
                    const annotation = getEffectiveAnnotation(
                      annotations,
                      regions,
                      region,
                    )
                    const isContinuation = region.region_role === "continuation"
                    const isSelected = selectedRegionId === region.id
                    return (
                      <button
                        key={region.id}
                        type="button"
                        className={cn(
                          "flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm hover:bg-muted/50",
                          isSelected && "bg-muted",
                        )}
                        data-testid={`review-region-list-${region.label}`}
                        onClick={() => {
                          setSelectedRegionId(region.id)
                          setPageNumber(getRegionPageNumber(region))
                        }}
                      >
                        <span className="min-w-0">
                          <span className="block truncate font-medium">
                            {isContinuation
                              ? region.label.replace("（续）", "（续页）")
                              : region.label}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            第 {region.page_number} 页
                            {isContinuation ? " · 与正题同一评分" : ""}
                          </span>
                        </span>
                        {annotation ? (
                          <Badge variant="secondary" className="capitalize">
                            {formatStatus(annotation.status)}
                          </Badge>
                        ) : (
                          <Badge variant="outline">未批注</Badge>
                        )}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>

            <div className="grid gap-4 rounded-md border p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium">
                    {selectedRegion
                      ? selectedRegion.region_role === "continuation"
                        ? selectedRegion.label.replace("（续）", "（续页）")
                        : selectedRegion.label
                      : "未选择题目区域"}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {selectedAnnotation
                      ? "正在编辑已保存的批注"
                      : "新建复核批注"}
                  </div>
                </div>
                {selectedAnnotation && (
                  <CheckCircle2 className="size-5 text-emerald-600" />
                )}
              </div>

              <AnnotationCropPreview
                examId={examId}
                submissionId={submissionId}
                annotation={selectedAnnotation}
              />

              {selectedRegion?.region_role === "continuation" && (
                <RegionCropPreview
                  examId={examId}
                  submissionId={submissionId}
                  region={selectedRegion}
                />
              )}

              <StandardAnswerReference answer={selectedStandardAnswer} />

              <AnnotationOcrDraft annotation={selectedAnnotation} />

              <GradingDraft
                annotation={selectedAnnotation}
                onApplySuggestion={() => {
                  if (selectedAnnotation?.suggested_score == null) return
                  setForm((current) => ({
                    ...current,
                    score: String(selectedAnnotation.suggested_score),
                    maxScore:
                      selectedAnnotation.max_score == null
                        ? current.maxScore
                        : String(selectedAnnotation.max_score),
                    comment:
                      selectedAnnotation.suggested_comment ?? current.comment,
                    status: "accepted",
                  }))
                }}
              />

              <div className="grid gap-2">
                <Label htmlFor="review-status">复核状态</Label>
                <Select
                  value={form.status}
                  onValueChange={(value) =>
                    setForm((current) => ({
                      ...current,
                      status: value as SubmissionAnnotationStatus,
                    }))
                  }
                  disabled={!selectedRegion}
                >
                  <SelectTrigger id="review-status" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="needs_review">待复核</SelectItem>
                    <SelectItem value="accepted">已通过</SelectItem>
                    <SelectItem value="rejected">已驳回</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-2">
                  <Label htmlFor="review-score">得分</Label>
                  <Input
                    id="review-score"
                    data-testid="review-score-input"
                    inputMode="decimal"
                    value={form.score}
                    disabled={!selectedRegion}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        score: event.target.value,
                      }))
                    }
                    placeholder="0"
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="review-max-score">满分</Label>
                  <Input
                    id="review-max-score"
                    data-testid="review-max-score-input"
                    inputMode="decimal"
                    value={form.maxScore}
                    disabled={!selectedRegion}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        maxScore: event.target.value,
                      }))
                    }
                    placeholder="5"
                  />
                </div>
              </div>

              <div className="grid gap-2">
                <Label htmlFor="review-comment">教师评语</Label>
                <textarea
                  id="review-comment"
                  data-testid="review-comment-input"
                  className="border-input placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 min-h-28 w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50"
                  value={form.comment}
                  disabled={!selectedRegion}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      comment: event.target.value,
                    }))
                  }
                  placeholder="请输入教师评语"
                />
              </div>

              <LoadingButton
                data-testid="review-save-annotation-button"
                loading={saveMutation.isPending}
                disabled={!selectedRegion}
                onClick={() => saveMutation.mutate()}
              >
                <MessageSquareText />
                保存批注
              </LoadingButton>
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}
