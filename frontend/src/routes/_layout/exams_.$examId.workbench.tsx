import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  BookOpen,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Flag,
  ImageOff,
  Loader2,
  Minus,
  PanelRightClose,
  PanelRightOpen,
  Plus,
  Undo2,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { z } from "zod"

import {
  type ExamRegionPublic,
  type ExamScoreSummaryRow,
  ExamsService,
  type StandardAnswerPublic,
  type SubmissionAnnotationPublic,
  type SubmissionAnnotationStatus,
} from "@/client"
import { Chip } from "@/components/Common/Chip"
import { EmptyState } from "@/components/Common/EmptyState"
import { Tag } from "@/components/Common/Tag"
import { useGradingAssignments } from "@/components/Exams/GradingAssignmentsCard"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import {
  fetchSubmissionAnnotationCropBlob,
  fetchSubmissionRegionCropBlob,
} from "@/lib/submission-media"
import { cn } from "@/lib/utils"
import { workflowApi } from "@/lib/workflow-api"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/exams_/$examId/workbench")({
  component: GradingWorkbench,
  validateSearch: z.object({
    filter: z.string().optional(),
    student: z.string().optional(),
  }),
  head: () => ({ meta: [{ title: "批卷工作台 - 点凡阅卷" }] }),
})

/** 学生筛选：全部 / 待复核（needs_review）/ 未批（尚无分数） */
type StudentFilter = "all" | "review" | "ungraded"

const FILTER_CHIPS: Array<[StudentFilter, string]> = [
  ["all", "全部"],
  ["review", "待复核"],
  ["ungraded", "未批"],
]

/** 一个学生（按 班级+姓名 合并多条 submission）在横批模式下的展示模型。 */
type WorkStudent = {
  key: string
  name: string
  className: string | null
  /** 工作对象：该生批注最多的 submission */
  submissionId: string
}

/** 横批矩阵中的一行：某学生在当前题上的批注（可能没有）。 */
type QuestionEntry = {
  student: WorkStudent
  annotation: SubmissionAnnotationPublic | null
}

type WorkQuestion = {
  label: string
  standardAnswer?: StandardAnswerPublic
  maxScore: number | null
  /** 已确认（accepted）人数 / 有该题批注的人数 */
  accepted: number
  total: number
}

const RUBRIC_OPEN_KEY = "dianfan.workbench.rubricOpen"
const rubricSeenKey = (examId: string) =>
  `dianfan.workbench.rubricSeen.${examId}`

/** 题号自然排序：按 label 中的数字段比较（"第2题" < "第10题"）。 */
function naturalLabelCompare(a: string, b: string) {
  const na = Number(a)
  const nb = Number(b)
  if (Number.isFinite(na) && Number.isFinite(nb)) return na - nb
  return a.localeCompare(b, "zh-Hans-CN", { numeric: true })
}

function formatScore(value: number | null | undefined) {
  if (value == null) return "—"
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function questionTitle(label: string) {
  return label.startsWith("第") || label.includes("题")
    ? label
    : `第 ${label} 题`
}

function annotationStatus(
  annotation: SubmissionAnnotationPublic,
): SubmissionAnnotationStatus {
  return annotation.status ?? "needs_review"
}

function scoringPointText(point: { [key: string]: unknown }) {
  const description =
    typeof point.description === "string"
      ? point.description
      : typeof point.text === "string"
        ? point.text
        : JSON.stringify(point)
  const points = typeof point.points === "number" ? point.points : null
  return { description, points }
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

/** 通用裁切图加载：blob → objectURL */
function useCropObjectUrl(queryKey: unknown[], queryFn: () => Promise<Blob>) {
  const [contentUrl, setContentUrl] = useState<string | null>(null)
  const query = useQuery({ queryKey, queryFn })
  const { data } = query
  useEffect(() => {
    if (!data) {
      setContentUrl(null)
      return
    }
    const url = URL.createObjectURL(data)
    setContentUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [data])
  return { ...query, contentUrl }
}

/**
 * 主裁切图查看器：滚轮缩放（0.5–3，以指针为中心）、按住拖动平移、双击复位。
 * 学生/题目切换时通过 resetKey 复位视图。
 */
function ZoomableCrop({
  examId,
  submissionId,
  annotation,
  resetKey,
}: {
  examId: string
  submissionId: string
  annotation: SubmissionAnnotationPublic
  resetKey: string
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 })
  const dragRef = useRef<{
    pointerId: number
    startX: number
    startY: number
    baseX: number
    baseY: number
  } | null>(null)

  const { isLoading, isError, contentUrl } = useCropObjectUrl(
    ["submission-annotation-crop", examId, submissionId, annotation.id],
    () =>
      fetchSubmissionAnnotationCropBlob(examId, submissionId, annotation.id),
  )

  // 切换学生/题目时复位缩放与平移
  // biome-ignore lint/correctness/useExhaustiveDependencies: resetKey 变化即复位
  useEffect(() => {
    setView({ scale: 1, x: 0, y: 0 })
  }, [resetKey, contentUrl])

  // 滚轮缩放需要 preventDefault，必须绑定非 passive 监听
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      const rect = el.getBoundingClientRect()
      const cx = event.clientX - rect.left - rect.width / 2
      const cy = event.clientY - rect.top - rect.height / 2
      setView((current) => {
        const next = clamp(
          current.scale * (event.deltaY < 0 ? 1.15 : 1 / 1.15),
          0.5,
          3,
        )
        const ratio = next / current.scale
        return {
          scale: next,
          x: cx - (cx - current.x) * ratio,
          y: cy - (cy - current.y) * ratio,
        }
      })
    }
    el.addEventListener("wheel", onWheel, { passive: false })
    return () => el.removeEventListener("wheel", onWheel)
  }, [])

  if (isError) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
        <ImageOff className="size-8 text-muted-foreground/50" />
        <p className="font-medium text-secondary-foreground text-sm">
          这份答卷的裁切图不可用
        </p>
        <p className="max-w-xs text-muted-foreground text-xs">
          可能是源页已被删除或该答卷来自旧数据，可切换其他学生继续批改
        </p>
      </div>
    )
  }
  if (isLoading || !contentUrl) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="size-4 animate-spin" />
        正在加载答题裁切图
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      role="application"
      aria-label="答题裁切图查看器（滚轮缩放、拖动平移、双击复位）"
      className="absolute inset-0 cursor-grab touch-none overflow-hidden active:cursor-grabbing"
      data-testid="wb-crop-viewport"
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture(event.pointerId)
        dragRef.current = {
          pointerId: event.pointerId,
          startX: event.clientX,
          startY: event.clientY,
          baseX: view.x,
          baseY: view.y,
        }
      }}
      onPointerMove={(event) => {
        const drag = dragRef.current
        if (!drag || drag.pointerId !== event.pointerId) return
        setView((current) => ({
          ...current,
          x: drag.baseX + event.clientX - drag.startX,
          y: drag.baseY + event.clientY - drag.startY,
        }))
      }}
      onPointerUp={(event) => {
        if (dragRef.current?.pointerId === event.pointerId) {
          dragRef.current = null
        }
      }}
      onPointerCancel={() => {
        dragRef.current = null
      }}
      onDoubleClick={() => setView({ scale: 1, x: 0, y: 0 })}
    >
      <div
        className="flex h-full w-full items-center justify-center"
        style={{
          transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
        }}
      >
        <img
          alt={`${annotation.label} 答题裁切图`}
          className="max-h-full max-w-full select-none object-contain"
          draggable={false}
          data-testid="wb-crop-image"
          src={contentUrl}
        />
      </div>
      {view.scale !== 1 && (
        <span className="absolute right-3 bottom-3 rounded-full border bg-background/85 px-2 py-0.5 text-muted-foreground text-xs tabular-nums">
          {Math.round(view.scale * 100)}%
        </span>
      )}
    </div>
  )
}

/** 续页区域裁切：与正题共享同一评分，接在主图下方连续滚动 */
function ContinuationCrop({
  examId,
  submissionId,
  region,
}: {
  examId: string
  submissionId: string
  region: ExamRegionPublic
}) {
  const { isLoading, isError, contentUrl } = useCropObjectUrl(
    ["submission-region-crop", examId, submissionId, region.id],
    () => fetchSubmissionRegionCropBlob(examId, submissionId, region.id),
  )

  if (isError) return null
  return (
    <div className="grid gap-1 px-4 pb-4">
      <div className="text-muted-foreground text-xs">
        续页（第 {region.page_number ?? 1} 页，与正题同一评分）
      </div>
      {isLoading || !contentUrl ? (
        <div className="flex items-center gap-2 rounded-md border p-3 text-muted-foreground text-xs">
          <Loader2 className="size-3 animate-spin" />
          正在加载续页裁切图
        </div>
      ) : (
        <div className="overflow-hidden rounded-md border bg-muted/20">
          <img
            alt={`${region.label} 续页裁切图`}
            className="block w-full"
            src={contentUrl}
          />
        </div>
      )}
    </div>
  )
}

function GradingWorkbench() {
  const { examId } = Route.useParams()
  // 从复核队列跳转时带 ?filter=needs_review，初始筛选直接落在「待复核」
  const search = Route.useSearch()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const [filter, setFilter] = useState<StudentFilter>(
    search.filter === "needs_review" ? "review" : "all",
  )
  const [classFilter, setClassFilter] = useState<string | null>(null)
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [commentDraft, setCommentDraft] = useState("")
  const [scoreInput, setScoreInput] = useState("")
  const [panelOpen, setPanelOpenState] = useState(
    () => localStorage.getItem(RUBRIC_OPEN_KEY) !== "0",
  )

  const setPanelOpen = (open: boolean) => {
    setPanelOpenState(open)
    localStorage.setItem(RUBRIC_OPEN_KEY, open ? "1" : "0")
  }

  const examQuery = useQuery({
    queryKey: ["exam", examId],
    queryFn: () => ExamsService.readExam({ examId }),
  })
  const { user } = useAuth()
  // 协作批卷：被分配的老师只见负责班级，顶部显示范围条
  const assignmentsQuery = useGradingAssignments(
    examId,
    Boolean(examQuery.data?.is_assigned),
  )
  const assignedClassNames = (assignmentsQuery.data?.assignments ?? []).filter(
    (item) => item.user_id === user?.id,
  )
  const submissionsQuery = useQuery({
    queryKey: ["student-submissions", examId],
    queryFn: () => ExamsService.readStudentSubmissions({ examId }),
  })
  const scoreSummaryQuery = useQuery({
    queryKey: ["exam-score-summary", examId],
    queryFn: () => ExamsService.readExamScoresSummary({ examId }),
  })
  const standardAnswersQuery = useQuery({
    queryKey: ["standard-answers", examId],
    queryFn: () => ExamsService.readStandardAnswers({ examId }),
  })

  // 一个学生可能有多条 submission（多张照片）：按 班级+姓名 分组，
  // 取批注最多的 submission 作为工作对象；按 班级+姓名 排序保证横批顺序稳定。
  const students = useMemo<WorkStudent[]>(() => {
    const summaryBySubmission = new Map<string, ExamScoreSummaryRow>(
      (scoreSummaryQuery.data?.data ?? []).map((row) => [
        row.submission_id,
        row,
      ]),
    )
    const groups = new Map<string, string[]>()
    const submissionById = new Map(
      (submissionsQuery.data?.data ?? []).map((submission) => [
        submission.id,
        submission,
      ]),
    )
    for (const submission of submissionsQuery.data?.data ?? []) {
      const key = `${submission.class_name ?? ""}::${submission.student_name ?? ""}`
      const group = groups.get(key) ?? []
      group.push(submission.id)
      groups.set(key, group)
    }
    const annotationCount = (submissionId: string) =>
      summaryBySubmission
        .get(submissionId)
        ?.questions?.filter((question) => question.annotation_id).length ?? 0
    return Array.from(groups.entries())
      .map(([key, submissionIds]) => {
        const workingId = submissionIds.reduce((best, id) =>
          annotationCount(id) > annotationCount(best) ? id : best,
        )
        const working = submissionById.get(workingId)
        return {
          key,
          name: working?.student_name || "未命名",
          className: working?.class_name ?? null,
          submissionId: workingId,
        }
      })
      .sort(
        (a, b) =>
          // 未分班排最后（多为测试/补录数据）
          (a.className ?? "￿").localeCompare(b.className ?? "￿", "zh-Hans-CN", {
            numeric: true,
          }) || a.name.localeCompare(b.name, "zh-Hans-CN"),
      )
  }, [submissionsQuery.data, scoreSummaryQuery.data])

  // 横批矩阵数据：一次请求拿全考试批注（替代逐学生 N+1），按 submission 归位
  const examAnnotationsQuery = useQuery({
    queryKey: ["exam-annotations", examId],
    queryFn: () =>
      workflowApi<{ data: SubmissionAnnotationPublic[] }>(
        `/exams/${examId}/annotations`,
      ),
  })

  const annotationsByStudent = useMemo(() => {
    const bySubmission = new Map<string, SubmissionAnnotationPublic[]>()
    for (const annotation of examAnnotationsQuery.data?.data ?? []) {
      const list = bySubmission.get(annotation.submission_id) ?? []
      list.push(annotation)
      bySubmission.set(annotation.submission_id, list)
    }
    return new Map<string, SubmissionAnnotationPublic[]>(
      students.map((student) => [
        student.key,
        bySubmission.get(student.submissionId) ?? [],
      ]),
    )
  }, [students, examAnnotationsQuery.data])

  const standardAnswersByRegionId = useMemo(
    () =>
      new Map(
        (standardAnswersQuery.data?.data ?? []).map((answer) => [
          answer.exam_region_id,
          answer,
        ]),
      ),
    [standardAnswersQuery.data?.data],
  )

  // 题目列表：全体学生批注 label 的并集（按 label 去重），按数字自然排序
  const questions = useMemo<WorkQuestion[]>(() => {
    const labelOrder: string[] = []
    const seenLabels = new Set<string>()
    const regionIdByLabel = new Map<string, string>()
    for (const annotations of annotationsByStudent.values()) {
      for (const annotation of annotations) {
        if (!seenLabels.has(annotation.label)) {
          seenLabels.add(annotation.label)
          labelOrder.push(annotation.label)
        }
        if (
          !regionIdByLabel.has(annotation.label) &&
          annotation.exam_region_id
        ) {
          regionIdByLabel.set(annotation.label, annotation.exam_region_id)
        }
      }
    }
    return labelOrder.sort(naturalLabelCompare).map((label) => {
      const standardAnswer = regionIdByLabel.get(label)
        ? standardAnswersByRegionId.get(regionIdByLabel.get(label))
        : undefined
      let accepted = 0
      let total = 0
      let maxScore: number | null = standardAnswer?.max_score ?? null
      for (const annotations of annotationsByStudent.values()) {
        const annotation = annotations.find((item) => item.label === label)
        if (!annotation) continue
        total += 1
        if (annotationStatus(annotation) === "accepted") accepted += 1
        maxScore = maxScore ?? annotation.max_score ?? null
      }
      return { label, standardAnswer, maxScore, accepted, total }
    })
  }, [annotationsByStudent, standardAnswersByRegionId])

  // 题目加载后默认选中第一题；题目消失时回退
  useEffect(() => {
    if (!questions.length) return
    if (!questions.some((question) => question.label === selectedLabel)) {
      setSelectedLabel(questions[0].label)
    }
  }, [questions, selectedLabel])

  const currentQuestion =
    questions.find((question) => question.label === selectedLabel) ?? null
  const questionIndex = questions.findIndex(
    (question) => question.label === selectedLabel,
  )

  // 当前题的横批行：每个学生一行（无批注的保留但不可选）
  const entries = useMemo<QuestionEntry[]>(
    () =>
      currentQuestion
        ? students.map((student) => ({
            student,
            annotation:
              annotationsByStudent
                .get(student.key)
                ?.find((item) => item.label === currentQuestion.label) ?? null,
          }))
        : [],
    [currentQuestion, students, annotationsByStudent],
  )

  const gradableEntries = useMemo(
    () => entries.filter((entry) => entry.annotation),
    [entries],
  )

  const filteredEntries = useMemo(() => {
    let list = gradableEntries
    if (filter === "review") {
      list = list.filter(
        (entry) =>
          entry.annotation &&
          annotationStatus(entry.annotation) === "needs_review",
      )
    } else if (filter === "ungraded") {
      list = list.filter(
        (entry) =>
          entry.annotation &&
          entry.annotation.score == null &&
          annotationStatus(entry.annotation) !== "needs_review",
      )
    }
    // 班级筛选（与状态筛选叠加；横批可按班进行）
    if (classFilter) {
      list = list.filter((entry) => entry.student.className === classFilter)
    }
    return list
  }, [gradableEntries, filter, classFilter])

  // 出现过的班级列表（用于班级筛选）
  const classOptions = useMemo(() => {
    const names = new Set<string>()
    for (const student of students) {
      if (student.className) names.add(student.className)
    }
    return Array.from(names).sort((a, b) =>
      a.localeCompare(b, "zh-Hans-CN", { numeric: true }),
    )
  }, [students])

  // 筛选/切题后若当前学生不在列表中，自动选中第一个
  useEffect(() => {
    if (!filteredEntries.length) return
    if (!filteredEntries.some((entry) => entry.student.key === selectedKey)) {
      setSelectedKey(filteredEntries[0].student.key)
    }
  }, [filteredEntries, selectedKey])

  // 从学生答卷/复核队列跳转时带 ?student=姓名，直接定位到该学生
  useEffect(() => {
    if (!search.student || !entries.length) return
    const hit = entries.find((entry) => entry.student.name === search.student)
    if (hit) setSelectedKey(hit.student.key)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search.student, entries.length, entries.find])

  const currentEntry =
    filteredEntries.find((entry) => entry.student.key === selectedKey) ??
    entries.find((entry) => entry.student.key === selectedKey) ??
    null
  const currentStudent = currentEntry?.student ?? null
  const currentAnnotation = currentEntry?.annotation ?? null
  const submissionId = currentStudent?.submissionId ?? null
  const studentIndex = filteredEntries.findIndex(
    (entry) => entry.student.key === selectedKey,
  )

  // 当前学生的模板区域：用于续页查找 + 保存时取最新几何
  const regionsQuery = useQuery({
    queryKey: ["workbench-regions", examId, submissionId],
    queryFn: () =>
      ExamsService.readStudentSubmissionTemplateRegions({
        examId,
        submissionId: submissionId as string,
      }),
    enabled: Boolean(submissionId),
  })
  const regions = useMemo(
    () => regionsQuery.data?.data ?? [],
    [regionsQuery.data?.data],
  )
  const regionsById = useMemo(
    () => new Map(regions.map((region) => [region.id, region])),
    [regions],
  )

  // 续页：与当前题同 question_key 的 continuation 区域
  const continuations = useMemo(() => {
    if (!currentAnnotation?.exam_region_id) return []
    const region = regionsById.get(currentAnnotation.exam_region_id)
    if (!region?.question_key) return []
    return regions.filter(
      (item) =>
        item.region_role === "continuation" &&
        item.question_key === region.question_key,
    )
  }, [currentAnnotation, regions, regionsById])

  // 面板记忆：每题首次进入默认展开；需要复核时自动展开
  // biome-ignore lint/correctness/useExhaustiveDependencies: 仅在题目切换时评估首访
  useEffect(() => {
    if (!currentQuestion) return
    const key = rubricSeenKey(examId)
    let seen: string[] = []
    try {
      seen = JSON.parse(localStorage.getItem(key) ?? "[]")
    } catch {
      seen = []
    }
    if (!seen.includes(currentQuestion.label)) {
      setPanelOpen(true)
      localStorage.setItem(
        key,
        JSON.stringify([...seen, currentQuestion.label]),
      )
    }
  }, [examId, currentQuestion?.label])

  const confidence =
    currentAnnotation?.grading_confidence ?? currentAnnotation?.ocr_confidence
  useEffect(() => {
    if (confidence != null && confidence < 0.8) {
      setPanelOpenState(true)
    }
  }, [confidence])

  // 批注切换时同步批注草稿 / 分数输入框
  useEffect(() => {
    setCommentDraft(currentAnnotation?.comment ?? "")
    setScoreInput(
      currentAnnotation?.score != null ? String(currentAnnotation.score) : "",
    )
  }, [currentAnnotation?.comment, currentAnnotation?.score])

  const saveMutation = useMutation({
    mutationFn: ({
      annotation,
      patch,
    }: {
      annotation: SubmissionAnnotationPublic
      patch: {
        score?: number | null
        status?: SubmissionAnnotationStatus
        comment?: string | null
      }
    }) => {
      const region = annotation.exam_region_id
        ? regionsById.get(annotation.exam_region_id)
        : undefined
      return ExamsService.updateSubmissionAnnotation({
        examId,
        submissionId: annotation.submission_id,
        annotationId: annotation.id,
        requestBody: {
          label: region?.label ?? annotation.label,
          status: patch.status ?? annotationStatus(annotation),
          page_number: region?.page_number ?? annotation.page_number,
          x: region?.x ?? annotation.x,
          y: region?.y ?? annotation.y,
          width: region?.width ?? annotation.width,
          height: region?.height ?? annotation.height,
          score:
            patch.score !== undefined
              ? patch.score
              : (annotation.score ?? null),
          max_score: currentQuestion?.maxScore ?? annotation.max_score ?? null,
          comment:
            patch.comment !== undefined
              ? patch.comment
              : (annotation.comment ?? null),
        },
      })
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["exam-annotations", examId],
      })
      queryClient.invalidateQueries({
        queryKey: ["exam-score-summary", examId],
      })
    },
  })

  /** 在筛选后的学生列表内移动（不循环） */
  const moveStudent = (direction: number) => {
    if (!filteredEntries.length) return
    const index = filteredEntries.findIndex(
      (entry) => entry.student.key === selectedKey,
    )
    const next = clamp(index + direction, 0, filteredEntries.length - 1)
    setSelectedKey(filteredEntries[next].student.key)
  }

  const moveQuestion = (direction: number) => {
    if (!questions.length) return
    const next = clamp(questionIndex + direction, 0, questions.length - 1)
    setSelectedLabel(questions[next].label)
  }

  /** 给分并保存（status=accepted），随后自动进入下一名学生 */
  const gradeAndAdvance = (score: number) => {
    if (!currentAnnotation) return
    saveMutation.mutate(
      { annotation: currentAnnotation, patch: { score, status: "accepted" } },
      {
        onSuccess: () => showSuccessToast(`已保存 ${formatScore(score)} 分`),
      },
    )
    moveStudent(1)
  }

  const adoptSuggested = () => {
    if (!currentAnnotation || currentAnnotation.suggested_score == null) return
    saveMutation.mutate(
      {
        annotation: currentAnnotation,
        patch: {
          score: currentAnnotation.suggested_score,
          status: "accepted",
          comment: currentAnnotation.comment?.trim()
            ? currentAnnotation.comment
            : (currentAnnotation.suggested_comment ?? null),
        },
      },
      {
        onSuccess: () =>
          showSuccessToast(
            `已采纳建议评分（${formatScore(currentAnnotation.suggested_score)} 分）`,
          ),
      },
    )
    moveStudent(1)
  }

  const flagReview = () => {
    if (!currentAnnotation) return
    saveMutation.mutate(
      {
        annotation: currentAnnotation,
        patch: { status: "needs_review" },
      },
      { onSuccess: () => showSuccessToast("已标记复核") },
    )
    moveStudent(1)
  }

  const saveComment = () => {
    if (!currentAnnotation) return
    const comment = commentDraft.trim()
    if (comment === (currentAnnotation.comment ?? "")) return
    saveMutation.mutate(
      {
        annotation: currentAnnotation,
        patch: { comment: comment || null },
      },
      { onSuccess: () => showSuccessToast("批注已保存") },
    )
  }

  // ---- 键盘快捷键（输入框聚焦时不生效）----
  // 0-9 给分（满分 >9 时支持两位快速连打）、A 采纳建议、F 标记复核、
  // 空格/→ 下一份、← 上一份
  const digitBufferRef = useRef("")
  const digitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const keyHandlerRef = useRef<(event: KeyboardEvent) => void>(() => {})
  keyHandlerRef.current = (event: KeyboardEvent) => {
    if (!currentAnnotation) return
    const maxScore = currentQuestion?.maxScore ?? null
    if (/^[0-9]$/.test(event.key) && maxScore != null) {
      event.preventDefault()
      if (digitTimerRef.current) clearTimeout(digitTimerRef.current)
      digitBufferRef.current += event.key
      const buffered = Number(digitBufferRef.current)
      const commit = () => {
        const value = Number(digitBufferRef.current)
        digitBufferRef.current = ""
        if (value <= maxScore) gradeAndAdvance(value)
      }
      // 单位数满分直接提交；缓冲再补一位也不可能合法时也直接提交
      if (maxScore <= 9 || buffered * 10 > maxScore) {
        commit()
      } else {
        digitTimerRef.current = setTimeout(commit, 600)
      }
      return
    }
    switch (event.key) {
      case "a":
      case "A":
        event.preventDefault()
        adoptSuggested()
        break
      case "f":
      case "F":
        event.preventDefault()
        flagReview()
        break
      case " ":
      case "ArrowRight":
        event.preventDefault()
        moveStudent(1)
        break
      case "ArrowLeft":
        event.preventDefault()
        moveStudent(-1)
        break
    }
  }
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable)
      ) {
        return
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return
      keyHandlerRef.current(event)
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [])

  const isLoading =
    examQuery.isLoading ||
    submissionsQuery.isLoading ||
    scoreSummaryQuery.isLoading

  // 分数按钮：整数满分且 ≤12 时 0..max 每分一个按钮，否则降级为数字输入 + 步进器
  const useScoreButtons =
    currentQuestion?.maxScore != null &&
    Number.isInteger(currentQuestion.maxScore) &&
    currentQuestion.maxScore <= 12
  const scoreOptions = useScoreButtons
    ? Array.from({ length: (currentQuestion?.maxScore ?? 0) + 1 }, (_, i) => i)
    : []

  const stepScoreInput = (delta: number) => {
    const max = currentQuestion?.maxScore ?? Number.POSITIVE_INFINITY
    const current = Number(scoreInput) || 0
    const next = clamp(Math.round((current + delta) * 2) / 2, 0, max)
    setScoreInput(String(next))
  }
  const commitScoreInput = (advance: boolean) => {
    const max = currentQuestion?.maxScore ?? Number.POSITIVE_INFINITY
    const value = Number(scoreInput)
    if (!scoreInput.trim() || !Number.isFinite(value)) return
    const clamped = clamp(value, 0, max)
    if (advance) {
      gradeAndAdvance(clamped)
    } else if (currentAnnotation) {
      saveMutation.mutate(
        {
          annotation: currentAnnotation,
          patch: { score: clamped, status: "accepted" },
        },
        {
          onSuccess: () =>
            showSuccessToast(`已保存 ${formatScore(clamped)} 分`),
        },
      )
    }
  }

  return (
    <div className="flex h-[calc(100dvh-12rem)] min-h-[30rem] flex-col gap-3">
      {/* 协作批卷范围条：被分配的老师只看到自己负责的班级 */}
      {examQuery.data?.is_assigned && assignedClassNames.length > 0 && (
        <div className="flex items-center gap-2 rounded-2xl border bg-card px-4 py-2 text-sm shadow-card">
          <Tag variant="neutral">协作</Tag>
          <span className="text-muted-foreground">
            你负责：
            {assignedClassNames.map((item) => item.class_name).join("、")}
          </span>
        </div>
      )}
      {/* 顶部固定栏：题目导航 + 进度 + 筛选 + 退出 */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border bg-card px-4 py-2.5 shadow-card">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" data-testid="wb-question-menu">
              {currentQuestion
                ? questionTitle(currentQuestion.label)
                : "选择题目"}
              <ChevronDown />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="start"
            className="max-h-96 overflow-y-auto"
          >
            {questions.map((question) => (
              <DropdownMenuItem
                key={question.label}
                onSelect={() => setSelectedLabel(question.label)}
              >
                <span className="flex-1">{questionTitle(question.label)}</span>
                <span className="ml-4 text-muted-foreground text-xs tabular-nums">
                  {question.accepted}/{question.total}
                </span>
                {question.label === selectedLabel && (
                  <Check className="ml-2 size-3.5" />
                )}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        {currentQuestion && (
          <div className="flex items-center gap-2">
            {currentQuestion.standardAnswer?.question_type && (
              <Tag variant="neutral">
                {currentQuestion.standardAnswer.question_type}
              </Tag>
            )}
            <span
              className="text-muted-foreground text-xs"
              data-testid="wb-question-meta"
            >
              满分 {formatScore(currentQuestion.maxScore)} 分
            </span>
          </div>
        )}

        <span
          className="text-muted-foreground text-xs tabular-nums"
          data-testid="wb-progress"
        >
          已批 {currentQuestion?.accepted ?? 0}/{currentQuestion?.total ?? 0}
        </span>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5">
            {FILTER_CHIPS.map(([value, label]) => (
              <Chip
                key={value}
                active={filter === value}
                data-testid={`wb-filter-${value}`}
                onClick={() => setFilter(value)}
              >
                {label}
              </Chip>
            ))}
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="icon"
              className="size-8"
              aria-label="上一题"
              disabled={questionIndex <= 0}
              onClick={() => moveQuestion(-1)}
            >
              <ChevronLeft />
            </Button>
            <Button
              variant="outline"
              size="icon"
              className="size-8"
              aria-label="下一题"
              disabled={questionIndex >= questions.length - 1}
              onClick={() => moveQuestion(1)}
            >
              <ChevronRight />
            </Button>
          </div>
          <Button
            variant="ghost"
            size="sm"
            data-testid="wb-rubric-toggle"
            onClick={() => setPanelOpen(!panelOpen)}
          >
            <BookOpen />
            评分规则
          </Button>
          <Button variant="ghost" size="sm" asChild>
            <Link to="/exams/$examId/grading" params={{ examId }}>
              <Undo2 />
              退出批改
            </Link>
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="flex flex-1 items-center justify-center gap-2 rounded-2xl border text-muted-foreground text-sm">
          <Loader2 className="size-4 animate-spin" />
          正在加载批卷工作台
        </div>
      ) : students.length === 0 ? (
        <EmptyState
          className="flex-1"
          title="还没有学生答卷"
          description="请先在导入中心上传学生答卷照片，再到批次管理发起批改"
        />
      ) : questions.length === 0 ? (
        <EmptyState
          className="flex-1"
          title="还没有题目批注"
          description="请先到「批次管理」运行自动批改，生成题目裁切与建议评分后再回到工作台"
        />
      ) : (
        <>
          {/* 中间主区域 + 右侧评分依据面板 */}
          <div className="flex min-h-0 flex-1 gap-3">
            {/* 左侧学生列表：与键盘翻页同一顺序，点选切换 */}
            <aside
              className="flex w-44 shrink-0 flex-col overflow-hidden rounded-2xl border bg-card shadow-card"
              data-testid="wb-student-rail"
            >
              <div className="border-b px-3 py-2.5 text-muted-foreground text-xs">
                学生（{filteredEntries.length}）
              </div>
              {classOptions.length > 1 && (
                <div className="flex flex-wrap gap-1 border-b px-2.5 py-2">
                  <button
                    type="button"
                    data-testid="wb-class-filter-all"
                    onClick={() => setClassFilter(null)}
                    className={cn(
                      "rounded-full px-2 py-0.5 text-xs transition-colors",
                      classFilter === null
                        ? "bg-primary text-primary-foreground"
                        : "bg-secondary text-secondary-foreground hover:bg-accent",
                    )}
                  >
                    全部
                  </button>
                  {classOptions.map((name) => (
                    <button
                      key={name}
                      type="button"
                      data-testid={`wb-class-filter-${name}`}
                      onClick={() =>
                        setClassFilter(classFilter === name ? null : name)
                      }
                      className={cn(
                        "rounded-full px-2 py-0.5 text-xs transition-colors",
                        classFilter === name
                          ? "bg-primary text-primary-foreground"
                          : "bg-secondary text-secondary-foreground hover:bg-accent",
                      )}
                    >
                      {name}
                    </button>
                  ))}
                </div>
              )}
              <div className="min-h-0 flex-1 overflow-y-auto">
                {filteredEntries.length === 0 ? (
                  <div className="px-3 py-6 text-center text-muted-foreground text-xs">
                    当前筛选下没有学生
                  </div>
                ) : (
                  filteredEntries.map((entry) => {
                    const active = entry.student.key === selectedKey
                    const annotation = entry.annotation
                    const needsReview =
                      annotation &&
                      annotationStatus(annotation) === "needs_review"
                    return (
                      <button
                        key={entry.student.key}
                        type="button"
                        data-testid={`wb-student-${entry.student.name}`}
                        onClick={() => setSelectedKey(entry.student.key)}
                        className={cn(
                          "flex w-full items-center gap-2 border-b px-3 py-2 text-left transition-colors hover:bg-accent",
                          active && "bg-accent font-medium",
                        )}
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm">
                            {entry.student.name}
                          </span>
                          <span className="text-muted-foreground text-xs">
                            {entry.student.className || "未分班"}
                          </span>
                        </span>
                        {needsReview ? (
                          <span
                            className="size-2 shrink-0 rounded-full bg-amber-500"
                            title="待复核"
                          />
                        ) : annotation?.score != null ? (
                          <span className="shrink-0 text-muted-foreground text-xs tabular-nums">
                            {formatScore(annotation.score)}
                          </span>
                        ) : (
                          <span className="shrink-0 text-muted-foreground text-xs">
                            —
                          </span>
                        )}
                      </button>
                    )
                  })
                )}
              </div>
            </aside>

            <main className="min-w-0 flex-1 overflow-hidden rounded-2xl border bg-card shadow-card">
              {filteredEntries.length === 0 ? (
                <div className="flex h-full items-center justify-center text-muted-foreground text-sm">
                  当前筛选下没有学生
                </div>
              ) : (
                <div className="h-full overflow-y-auto">
                  <div className="flex min-h-full flex-col">
                    <div className="relative min-h-80 flex-1">
                      {currentAnnotation && submissionId ? (
                        <ZoomableCrop
                          examId={examId}
                          submissionId={submissionId}
                          annotation={currentAnnotation}
                          resetKey={currentAnnotation.id}
                        />
                      ) : (
                        <div className="flex h-full items-center justify-center text-muted-foreground text-sm">
                          该生本题暂无批注
                        </div>
                      )}
                    </div>
                    {currentStudent && (
                      <div
                        className="px-4 py-2 text-center text-muted-foreground text-xs"
                        data-testid="wb-student-caption"
                      >
                        {currentStudent.name} ·{" "}
                        {currentStudent.className || "未分班"}
                        {studentIndex >= 0 &&
                          ` · ${studentIndex + 1}/${filteredEntries.length}`}
                      </div>
                    )}
                    {submissionId &&
                      continuations.map((region) => (
                        <ContinuationCrop
                          key={region.id}
                          examId={examId}
                          submissionId={submissionId}
                          region={region}
                        />
                      ))}
                  </div>
                </div>
              )}
            </main>

            {/* 评分依据面板：默认收起为窄条，点击展开 */}
            {panelOpen ? (
              <aside
                className="flex w-[340px] shrink-0 flex-col overflow-hidden rounded-2xl border bg-card shadow-card"
                data-testid="wb-rubric-panel"
              >
                <div className="flex items-center gap-2 border-b px-4 py-2.5">
                  <BookOpen className="size-4 text-primary" />
                  <span className="font-semibold text-sm">评分依据</span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="ml-auto size-7"
                    aria-label="收起评分依据"
                    onClick={() => setPanelOpen(false)}
                  >
                    <PanelRightClose />
                  </Button>
                </div>
                <div className="grid flex-1 content-start gap-4 overflow-y-auto p-4">
                  {confidence != null && confidence < 0.8 && (
                    <div className="flex items-center gap-2 rounded-md border border-amber-300/60 bg-amber-500/10 px-3 py-2 text-amber-700 text-xs dark:text-amber-400">
                      建议人工确认此题评分
                    </div>
                  )}

                  <section className="grid content-start gap-1.5">
                    <span className="font-medium text-xs">标准答案</span>
                    {currentQuestion?.standardAnswer ? (
                      <div className="max-h-44 overflow-auto whitespace-pre-wrap rounded-md border bg-muted/30 p-2.5 text-muted-foreground text-xs">
                        {currentQuestion.standardAnswer.answer_text}
                      </div>
                    ) : (
                      <div className="text-muted-foreground text-xs">
                        该题还没有标准答案
                      </div>
                    )}
                  </section>

                  {(currentQuestion?.standardAnswer?.scoring_points?.length ??
                    0) > 0 && (
                    <section className="grid content-start gap-1.5">
                      <span className="font-medium text-xs">评分要点</span>
                      <ul className="grid gap-1">
                        {currentQuestion?.standardAnswer?.scoring_points?.map(
                          (point, index) => {
                            const { description, points } =
                              scoringPointText(point)
                            return (
                              <li
                                key={`point-${index}`}
                                className="flex items-start gap-1.5 text-xs"
                              >
                                <Check className="mt-0.5 size-3 shrink-0 text-emerald-600" />
                                <span className="text-muted-foreground">
                                  {description}
                                  {points != null && (
                                    <span className="text-foreground">{`（${points} 分）`}</span>
                                  )}
                                </span>
                              </li>
                            )
                          },
                        )}
                      </ul>
                    </section>
                  )}

                  <section className="grid content-start gap-1.5">
                    <span className="font-medium text-xs">识别结果</span>
                    {currentAnnotation?.ocr_text?.trim() ? (
                      <div className="max-h-44 overflow-auto whitespace-pre-wrap rounded-md border p-2.5 text-muted-foreground text-xs">
                        {currentAnnotation.ocr_text}
                      </div>
                    ) : (
                      <div className="text-muted-foreground text-xs">
                        暂无识别文本
                      </div>
                    )}
                  </section>

                  {currentAnnotation?.suggested_score != null && (
                    <section className="grid content-start gap-1.5 rounded-md border bg-muted/30 p-3">
                      <div className="flex items-baseline gap-1.5">
                        <span className="font-medium text-xs">建议评分</span>
                        <span className="font-bold text-lg tabular-nums">
                          {formatScore(currentAnnotation.suggested_score)}
                        </span>
                        <span className="text-muted-foreground text-xs">
                          / {formatScore(currentQuestion?.maxScore)}
                        </span>
                      </div>
                      {currentAnnotation.suggested_comment && (
                        <p className="whitespace-pre-wrap text-muted-foreground text-xs">
                          {currentAnnotation.suggested_comment}
                        </p>
                      )}
                    </section>
                  )}

                  <section className="grid content-start gap-1.5">
                    <span className="font-medium text-xs">教师批注</span>
                    <textarea
                      className="field-sizing-content min-h-16 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
                      data-testid="wb-comment"
                      placeholder="给学生的评语（可选，失焦自动保存）…"
                      value={commentDraft}
                      onChange={(event) => setCommentDraft(event.target.value)}
                      onBlur={saveComment}
                    />
                  </section>
                </div>
              </aside>
            ) : (
              <button
                type="button"
                className="flex w-9 shrink-0 flex-col items-center gap-2 rounded-2xl border bg-card py-3 text-muted-foreground text-xs shadow-card transition-colors hover:bg-muted/60"
                data-testid="wb-rubric-collapsed"
                onClick={() => setPanelOpen(true)}
              >
                <PanelRightOpen className="size-4" />
                <span className="[writing-mode:vertical-rl]">评分依据</span>
              </button>
            )}
          </div>

          {/* 底部固定评分栏 */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border bg-card px-4 py-3 shadow-card">
            {useScoreButtons ? (
              <div className="flex flex-wrap items-center gap-1.5">
                {scoreOptions.map((value) => {
                  const active = currentAnnotation?.score === value
                  return (
                    <button
                      key={value}
                      type="button"
                      className={cn(
                        "h-9 min-w-9 rounded-lg border px-2 font-medium text-sm tabular-nums transition-colors",
                        active
                          ? "border-primary bg-primary text-primary-foreground"
                          : "bg-background hover:border-primary/50 hover:text-primary",
                      )}
                      data-testid={`wb-score-${value}`}
                      disabled={!currentAnnotation}
                      onClick={() => gradeAndAdvance(value)}
                    >
                      {value}
                    </button>
                  )
                })}
              </div>
            ) : (
              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="icon"
                  className="size-8"
                  aria-label="减分"
                  disabled={!currentAnnotation}
                  onClick={() => stepScoreInput(-0.5)}
                >
                  <Minus />
                </Button>
                <Input
                  className="h-9 w-20 text-center tabular-nums"
                  data-testid="wb-score-input"
                  inputMode="decimal"
                  placeholder="分数"
                  value={scoreInput}
                  disabled={!currentAnnotation}
                  onChange={(event) => setScoreInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") commitScoreInput(true)
                  }}
                  onBlur={() => commitScoreInput(false)}
                />
                <Button
                  variant="outline"
                  size="icon"
                  className="size-8"
                  aria-label="加分"
                  disabled={!currentAnnotation}
                  onClick={() => stepScoreInput(0.5)}
                >
                  <Plus />
                </Button>
                <span className="text-muted-foreground text-xs">
                  / {formatScore(currentQuestion?.maxScore)} 分（回车保存）
                </span>
              </div>
            )}

            {currentAnnotation?.suggested_score != null && (
              <Button
                variant="outline"
                size="sm"
                className="border-primary/60 font-semibold text-primary hover:bg-primary/10"
                data-testid="wb-adopt"
                onClick={adoptSuggested}
              >
                建议：{formatScore(currentAnnotation.suggested_score)} 分
              </Button>
            )}

            <div className="ml-auto flex items-center gap-2">
              {confidence != null && confidence < 0.8 && (
                <Tag variant="amber">请复核</Tag>
              )}
              <Button
                variant="outline"
                size="sm"
                data-testid="wb-flag"
                disabled={!currentAnnotation}
                onClick={flagReview}
              >
                <Flag
                  className={cn(
                    currentAnnotation &&
                      annotationStatus(currentAnnotation) === "needs_review" &&
                      "text-amber-500",
                  )}
                />
                标记复核
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
