import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ArrowLeft,
  CheckCircle2,
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
        title: "Review Submission - AI Exam Grader",
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

function formatStatus(status?: string | null) {
  return (status || "needs_review").replace(/_/g, " ")
}

function formatTaskProgress(task?: ProcessingTaskPublic | null) {
  if (!task) return "No task yet"
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
    <div className="grid gap-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm text-muted-foreground">
          Page {pageNumber} of {pageCount}
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={pageNumber <= 1}
            onClick={() => setPageNumber(Math.max(1, pageNumber - 1))}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={pageNumber >= pageCount}
            onClick={() => setPageNumber(Math.min(pageCount, pageNumber + 1))}
          >
            Next
          </Button>
        </div>
      </div>
      {isError ? (
        <div className="rounded-md border p-8 text-sm text-destructive">
          Failed to load submission preview.
        </div>
      ) : isLoading || !contentUrl ? (
        <div className="flex items-center gap-2 rounded-md border p-8 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Loading review preview
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
          No template regions on this page yet.
        </div>
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
  const selectedRegion = regions.find(
    (region) => region.id === selectedRegionId,
  )
  const selectedAnnotation = selectedRegion
    ? getRegionAnnotation(annotations, selectedRegion.id)
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
      if (!selectedRegion) {
        throw new Error("Select a template region before saving")
      }
      const requestBody = {
        label: selectedRegion.label,
        status: form.status,
        page_number: getRegionPageNumber(selectedRegion),
        x: selectedRegion.x,
        y: selectedRegion.y,
        width: selectedRegion.width,
        height: selectedRegion.height,
        score: toOptionalNumber(form.score),
        max_score: toOptionalNumber(form.maxScore),
        comment: form.comment.trim() || null,
        exam_region_id: selectedRegion.id,
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
      showSuccessToast("Annotation saved")
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
      showSuccessToast("Submission processing task started")
      queryClient.invalidateQueries({
        queryKey: ["submission-annotations", examId, submissionId],
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
    }
  }, [examId, processingTaskQuery.data?.status, queryClient, submissionId])

  const isLoading =
    examQuery.isLoading ||
    submissionQuery.isLoading ||
    regionsQuery.isLoading ||
    annotationsQuery.isLoading

  return (
    <div className="grid gap-6">
      <div>
        <Button variant="ghost" size="sm" asChild className="-ml-3 mb-2">
          <Link to="/exams">
            <ArrowLeft />
            Exams
          </Link>
        </Button>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              {examQuery.data?.title ?? "Submission Review"}
            </h1>
            <p className="text-muted-foreground">
              {submission?.student_name || "Unnamed student"} ·{" "}
              {submission?.student_identifier || "No student ID"}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline" className="capitalize">
              {(submission?.status ?? "registration_pending").replace(
                /_/g,
                " ",
              )}
            </Badge>
            <Badge variant="secondary" className="capitalize">
              {(submission?.registration_status ?? "pending").replace(
                /_/g,
                " ",
              )}
            </Badge>
          </div>
        </div>
      </div>

      {isLoading || !submission ? (
        <div className="flex items-center gap-2 rounded-md border p-8 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Loading review workspace
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
                  <div className="text-sm font-medium">Processing pipeline</div>
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
                Run Processing
              </LoadingButton>
            </div>

            <div className="rounded-md border">
              <div className="flex items-center justify-between border-b px-4 py-3">
                <span className="text-sm font-medium">Template regions</span>
                <Badge variant="secondary">{regions.length}</Badge>
              </div>
              {regions.length === 0 ? (
                <div className="px-4 py-8 text-sm text-muted-foreground">
                  Mark template regions before reviewing submissions.
                </div>
              ) : (
                <div className="divide-y">
                  {regions.map((region) => {
                    const annotation = getRegionAnnotation(
                      annotations,
                      region.id,
                    )
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
                            {region.label}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            Page {region.page_number}
                          </span>
                        </span>
                        {annotation ? (
                          <Badge variant="secondary" className="capitalize">
                            {formatStatus(annotation.status)}
                          </Badge>
                        ) : (
                          <Badge variant="outline">No note</Badge>
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
                    {selectedRegion?.label ?? "No region selected"}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {selectedAnnotation
                      ? "Editing saved annotation"
                      : "Create review annotation"}
                  </div>
                </div>
                {selectedAnnotation && (
                  <CheckCircle2 className="size-5 text-emerald-600" />
                )}
              </div>

              <div className="grid gap-2">
                <Label htmlFor="review-status">Status</Label>
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
                    <SelectItem value="needs_review">Needs review</SelectItem>
                    <SelectItem value="accepted">Accepted</SelectItem>
                    <SelectItem value="rejected">Rejected</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-2">
                  <Label htmlFor="review-score">Score</Label>
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
                  <Label htmlFor="review-max-score">Max</Label>
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
                <Label htmlFor="review-comment">Comment</Label>
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
                  placeholder="Teacher feedback"
                />
              </div>

              <LoadingButton
                data-testid="review-save-annotation-button"
                loading={saveMutation.isPending}
                disabled={!selectedRegion}
                onClick={() => saveMutation.mutate()}
              >
                <MessageSquareText />
                Save Annotation
              </LoadingButton>
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}
