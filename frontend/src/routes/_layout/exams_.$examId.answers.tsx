import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  FileCheck2,
  Loader2,
  Save,
  Trash2,
} from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import {
  type ExamRegionPublic,
  ExamsService,
  type StandardAnswerPublic,
  type StandardAnswerStatus,
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

export const Route = createFileRoute("/_layout/exams_/$examId/answers")({
  component: StandardAnswerWorkspace,
  head: () => ({
    meta: [
      {
        title: "Standard Answers - AI Exam Grader",
      },
    ],
  }),
})

type AnswerForm = {
  answerText: string
  maxScore: string
  rubricText: string
  scoringPointsText: string
  status: StandardAnswerStatus
}

type ScoringPoint = {
  id: string
  description: string
  points: number
  required: boolean
}

function toForm(answer?: StandardAnswerPublic): AnswerForm {
  return {
    answerText: answer?.answer_text ?? "",
    maxScore: answer ? String(answer.max_score) : "",
    rubricText: answer?.rubric_text ?? "",
    scoringPointsText: scoringPointsToText(answer?.scoring_points),
    status: answer?.status ?? "draft",
  }
}

function scoringPointsToText(
  points?: StandardAnswerPublic["scoring_points"],
): string {
  if (!points?.length) return ""
  return points
    .map((point, index) => {
      const scoringPoint = point as Partial<ScoringPoint>
      return [
        scoringPoint.id || `point-${index + 1}`,
        scoringPoint.points ?? 0,
        scoringPoint.required === false ? "optional" : "required",
        scoringPoint.description ?? "",
      ].join(" | ")
    })
    .join("\n")
}

function parseBooleanFlag(value: string): boolean {
  return !["optional", "false", "no", "0"].includes(value.trim().toLowerCase())
}

function parseScoringPoints(text: string): ScoringPoint[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const parts = line.split("|").map((part) => part.trim())
      if (parts.length < 4) {
        throw new Error(
          `Scoring point ${index + 1} must use id | points | required | description`,
        )
      }
      const points = Number(parts[1])
      if (!Number.isFinite(points) || points < 0) {
        throw new Error(`Scoring point ${index + 1} has an invalid score`)
      }
      const description = parts.slice(3).join(" | ").trim()
      if (!parts[0] || !description) {
        throw new Error(`Scoring point ${index + 1} is incomplete`)
      }
      return {
        id: parts[0],
        points,
        required: parseBooleanFlag(parts[2]),
        description,
      }
    })
}

function getAnswerStatus(answer?: StandardAnswerPublic) {
  if (!answer) {
    return { label: "Missing", variant: "outline" as const }
  }
  if (answer.status === "ready") {
    return { label: "Ready", variant: "secondary" as const }
  }
  return { label: "Draft", variant: "outline" as const }
}

function getRegionPage(region: ExamRegionPublic) {
  return region.page_number ?? 1
}

function StandardAnswerWorkspace() {
  const { examId } = Route.useParams()
  const [selectedRegionId, setSelectedRegionId] = useState<string | null>(null)
  const [form, setForm] = useState<AnswerForm>(toForm())
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const examQuery = useQuery({
    queryKey: ["exam", examId],
    queryFn: () => ExamsService.readExam({ examId }),
  })
  const regionsQuery = useQuery({
    queryKey: ["exam-regions", examId],
    queryFn: () => ExamsService.readExamRegions({ examId }),
  })
  const answersQuery = useQuery({
    queryKey: ["standard-answers", examId],
    queryFn: () => ExamsService.readStandardAnswers({ examId }),
  })

  const questionRegions = useMemo(
    () =>
      (regionsQuery.data?.data ?? []).filter(
        (region) => region.region_type === "question",
      ),
    [regionsQuery.data?.data],
  )
  const answersByRegionId = useMemo(() => {
    return new Map(
      (answersQuery.data?.data ?? []).map((answer) => [
        answer.exam_region_id,
        answer,
      ]),
    )
  }, [answersQuery.data?.data])

  const selectedRegion = questionRegions.find(
    (region) => region.id === selectedRegionId,
  )
  const selectedAnswer = selectedRegion
    ? answersByRegionId.get(selectedRegion.id)
    : undefined
  const readyCount = questionRegions.filter(
    (region) => answersByRegionId.get(region.id)?.status === "ready",
  ).length
  const draftCount = questionRegions.filter(
    (region) => answersByRegionId.get(region.id)?.status === "draft",
  ).length
  const missingCount = questionRegions.length - readyCount - draftCount

  useEffect(() => {
    if (!selectedRegionId && questionRegions.length > 0) {
      setSelectedRegionId(questionRegions[0].id)
    }
  }, [questionRegions, selectedRegionId])

  useEffect(() => {
    setForm(toForm(selectedAnswer))
  }, [selectedAnswer])

  const saveMutation = useMutation({
    mutationFn: () => {
      if (!selectedRegion) {
        throw new Error("Select a question region before saving")
      }
      const maxScore = Number(form.maxScore)
      if (!Number.isFinite(maxScore) || maxScore <= 0) {
        throw new Error("Max score must be greater than 0")
      }
      const requestBody = {
        answer_text: form.answerText.trim(),
        max_score: maxScore,
        rubric_text: form.rubricText.trim() || null,
        scoring_points: parseScoringPoints(form.scoringPointsText),
        status: form.status,
      }
      if (!requestBody.answer_text) {
        throw new Error("Answer text is required")
      }
      if (selectedAnswer) {
        return ExamsService.updateStandardAnswer({
          examId,
          answerId: selectedAnswer.id,
          requestBody,
        })
      }
      return ExamsService.createStandardAnswer({
        examId,
        requestBody: {
          ...requestBody,
          exam_region_id: selectedRegion.id,
        },
      })
    },
    onSuccess: () => {
      showSuccessToast("Standard answer saved")
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["standard-answers", examId] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => {
      if (!selectedAnswer) {
        throw new Error("No standard answer to delete")
      }
      return ExamsService.deleteStandardAnswer({
        examId,
        answerId: selectedAnswer.id,
      })
    },
    onSuccess: () => {
      showSuccessToast("Standard answer deleted")
      setForm(toForm())
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["standard-answers", examId] })
    },
  })

  const isLoading =
    examQuery.isLoading || regionsQuery.isLoading || answersQuery.isLoading

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
              {examQuery.data?.title ?? "Standard Answers"}
            </h1>
            <p className="text-muted-foreground">
              Prepare one answer key for each question region.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary">{readyCount} ready</Badge>
            <Badge variant="outline">{draftCount} draft</Badge>
            <Badge variant={missingCount > 0 ? "destructive" : "secondary"}>
              {missingCount} missing
            </Badge>
          </div>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center gap-2 rounded-md border p-8 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Loading answer workspace
        </div>
      ) : questionRegions.length === 0 ? (
        <div className="grid gap-4 rounded-md border p-8">
          <FileCheck2 className="size-6 text-muted-foreground" />
          <div>
            <div className="text-sm font-medium">No question regions</div>
            <div className="text-sm text-muted-foreground">
              Mark question regions before preparing standard answers.
            </div>
          </div>
          <div>
            <Button asChild>
              <Link to="/exams/$examId/marking" params={{ examId }}>
                Open Marking
              </Link>
            </Button>
          </div>
        </div>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
          <aside className="rounded-md border">
            <div className="flex items-center justify-between border-b px-4 py-3">
              <span className="text-sm font-medium">Question regions</span>
              <Badge variant="secondary">{questionRegions.length}</Badge>
            </div>
            <div className="divide-y">
              {questionRegions.map((region) => {
                const answer = answersByRegionId.get(region.id)
                const status = getAnswerStatus(answer)
                const isSelected = selectedRegionId === region.id
                return (
                  <button
                    key={region.id}
                    type="button"
                    className={cn(
                      "flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm hover:bg-muted/50",
                      isSelected && "bg-muted",
                    )}
                    data-testid={`answer-region-list-${region.label}`}
                    onClick={() => setSelectedRegionId(region.id)}
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-medium">
                        {region.label}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        Page {getRegionPage(region)}
                      </span>
                    </span>
                    <Badge variant={status.variant}>{status.label}</Badge>
                  </button>
                )
              })}
            </div>
          </aside>

          <section className="grid gap-4 rounded-md border p-4">
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div>
                <div className="text-sm font-medium">
                  {selectedRegion?.label ?? "No region selected"}
                </div>
                <div className="text-xs text-muted-foreground">
                  {selectedAnswer
                    ? "Editing saved standard answer"
                    : "Create standard answer"}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {selectedAnswer?.status === "ready" ? (
                  <CheckCircle2 className="size-5 text-emerald-600" />
                ) : (
                  <AlertCircle className="size-5 text-muted-foreground" />
                )}
                {selectedAnswer && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => deleteMutation.mutate()}
                    disabled={deleteMutation.isPending}
                  >
                    <Trash2 />
                    Delete
                  </Button>
                )}
              </div>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="answer-text">Answer</Label>
              <textarea
                id="answer-text"
                data-testid="standard-answer-text"
                className="border-input placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 min-h-32 w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50"
                value={form.answerText}
                disabled={!selectedRegion}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    answerText: event.target.value,
                  }))
                }
                placeholder="Reference answer"
              />
            </div>

            <div className="grid gap-3 md:grid-cols-[160px_180px_minmax(0,1fr)]">
              <div className="grid gap-2">
                <Label htmlFor="answer-max-score">Max score</Label>
                <Input
                  id="answer-max-score"
                  data-testid="standard-answer-max-score"
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
              <div className="grid gap-2">
                <Label htmlFor="answer-status">Status</Label>
                <Select
                  value={form.status}
                  onValueChange={(value) =>
                    setForm((current) => ({
                      ...current,
                      status: value as StandardAnswerStatus,
                    }))
                  }
                  disabled={!selectedRegion}
                >
                  <SelectTrigger id="answer-status" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="draft">Draft</SelectItem>
                    <SelectItem value="ready">Ready</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="answer-rubric">Rubric</Label>
                <Input
                  id="answer-rubric"
                  data-testid="standard-answer-rubric"
                  value={form.rubricText}
                  disabled={!selectedRegion}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      rubricText: event.target.value,
                    }))
                  }
                  placeholder="Scoring rule"
                />
              </div>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="answer-scoring-points">Scoring points</Label>
              <textarea
                id="answer-scoring-points"
                data-testid="standard-answer-scoring-points"
                className="border-input placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 min-h-28 w-full rounded-md border bg-transparent px-3 py-2 font-mono text-xs shadow-xs outline-none focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50"
                value={form.scoringPointsText}
                disabled={!selectedRegion}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    scoringPointsText: event.target.value,
                  }))
                }
                placeholder="point-1 | 2 | required | Writes the correct formula"
              />
            </div>

            <LoadingButton
              data-testid="standard-answer-save-button"
              loading={saveMutation.isPending}
              disabled={!selectedRegion}
              onClick={() => saveMutation.mutate()}
            >
              <Save />
              Save Standard Answer
            </LoadingButton>
          </section>
        </div>
      )}
    </div>
  )
}
