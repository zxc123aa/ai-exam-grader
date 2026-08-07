import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  PenLine,
  Play,
  RefreshCw,
  Send,
} from "lucide-react"
import { useMemo, useState } from "react"

import { ExamsService } from "@/client"
import { resolveRole } from "@/components/Admin/roleMeta"
import { EmptyState } from "@/components/Common/EmptyState"
import { PageHead } from "@/components/Common/PageHead"
import { ProgressBar } from "@/components/Common/ProgressBar"
import { Tag, type TagVariant } from "@/components/Common/Tag"
import {
  GradingAssignmentsCard,
  useGradingAssignments,
} from "@/components/Exams/GradingAssignmentsCard"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { workflowApi } from "@/lib/workflow-api"

export const Route = createFileRoute("/_layout/exams_/$examId/grading")({
  component: GradingWorkspace,
  head: () => ({ meta: [{ title: "批量批改 - 点凡阅卷" }] }),
})

type Run = {
  id: string
  status: string
  provider: string
  model: string
  total_submissions: number
  completed_count: number
  review_count: number
  failed_count: number
  average_confidence: number | null
  total_items: number
  completed_items: number
  extracted_items: number
  objective_items: number
  subjective_items: number
  current_concurrency: number
  throttle_count: number
  config_snapshot?: Record<string, unknown>
  timing?: {
    layout_ms?: number
    crop_ms?: number
    ocr_ms?: number
    total_elapsed_ms?: number
    item_elapsed_ms?: number
    layoutMs?: number
    cropMs?: number
    ocrMs?: number
    totalElapsedMs?: number
    fallback_used?: boolean
  }
}
type ReviewItem = {
  submission_id: string
  student_name: string | null
  student_identifier: string | null
  label: string | null
  score: number | null
  max_score: number | null
  confidence: number | null
  risk: string
  priority: number
}
type ScoreRelease = {
  id: string
  version: number
  status: "published" | "superseded"
  item_count: number
  published_at: string
}
const gradingRunStatusTags: Record<
  string,
  { label: string; variant: TagVariant }
> = {
  awaiting_credits: { label: "等待服务资源", variant: "amber" },
  queued: { label: "排队中", variant: "indigo" },
  running: { label: "批改中", variant: "sky" },
  completed: { label: "已完成", variant: "mint" },
  completed_with_errors: { label: "已完成（部分失败）", variant: "amber" },
  failed: { label: "失败", variant: "red" },
}

/**
 * 复核原因 → 老师看得懂的文案（唯一的映射处）。
 * 后端只给风险类别与综合判断：镜像/配准异常归为「答案字迹不清」，
 * 得分压在 0 分或满分边界的归为「分数接近边界」，
 * 其余自动处理异常归为「评分依据不足」。
 */
function reviewReasonText(item: ReviewItem): string {
  if (item.risk === "镜像/配准异常") return "答案字迹不清"
  if (
    item.score != null &&
    item.max_score != null &&
    (item.score === 0 || item.score === item.max_score)
  ) {
    return "分数接近边界，建议复核"
  }
  return "评分依据不足"
}
const registrationTags: Record<string, { label: string; variant: TagVariant }> =
  {
    failed: { label: "配准失败", variant: "red" },
    manual_confirmed: { label: "人工配准", variant: "pink" },
    auto_confirmed: { label: "自动配准", variant: "mint" },
  }
const pendingRegistrationTag = {
  label: "待配准",
  variant: "amber" as TagVariant,
}
function GradingWorkspace() {
  const { examId } = Route.useParams()
  const client = useQueryClient()
  const { user } = useAuth()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [publishDialogOpen, setPublishDialogOpen] = useState(false)
  // 分配管理仅管理角色；老师只看到面向批改任务的业务设置。
  const role = user ? resolveRole(user) : "teacher"
  const isManager = ["school_owner", "school_admin"].includes(role)
  const examQuery = useQuery({
    queryKey: ["exam", examId],
    queryFn: () => ExamsService.readExam({ examId }),
  })
  const canManageAssignments =
    isManager || (user != null && examQuery.data?.owner_id === user.id)
  const canPublishScores =
    role === "school_owner" ||
    (user != null && examQuery.data?.owner_id === user.id)
  const assignmentsQuery = useGradingAssignments(examId, canManageAssignments)
  // 共享批卷开启但未分完时后端会 400，前端在按钮旁先提示
  const unassignedCount =
    (assignmentsQuery.data?.enabled &&
      assignmentsQuery.data?.unassigned?.length) ||
    0
  const runs = useQuery({
    queryKey: ["grading-runs", examId],
    queryFn: () =>
      workflowApi<{ data: Run[] }>(`/grading/runs?exam_id=${examId}`),
    refetchInterval: 3000,
  })
  const scoreSummary = useQuery({
    queryKey: ["exam-score-summary", examId],
    queryFn: () => ExamsService.readExamScoresSummary({ examId }),
    refetchInterval: 10000,
  })
  const currentRelease = useQuery({
    queryKey: ["score-release", examId],
    queryFn: () =>
      workflowApi<ScoreRelease | null>(
        `/grading/exams/${examId}/score-releases/current`,
      ),
    enabled: canPublishScores,
  })
  // 一个学生多张照片 = 多条 submission，列表按 班级+姓名 合并展示：
  // 配准取最差状态，得分求和，复核链接指向该学生第一条答卷。
  const formatRegistrationNotes = (notes: string | null) => {
    if (!notes) return null
    // 兼容早期英文备注："Preprocessed from mobile photo; pages=2, spread=2556x1558, ..."
    const legacy = notes.match(
      /^Preprocessed from mobile photo; pages=(\d+), spread=(\d+x\d+), scan_quality=(\w+), status=(\w+)$/,
    )
    if (legacy) {
      const quality =
        { pass: "通过", warn: "注意", fail: "未通过" }[legacy[3]] ?? legacy[3]
      return `手机照片已预处理；分割为 ${legacy[1]} 页，原图 ${legacy[2]}，扫描质量：${quality}，状态：${legacy[4]}`
    }
    return notes
  }
  const mergedStudents = useMemo(() => {
    const rows = scoreSummary.data?.data ?? []
    const map = new Map<
      string,
      {
        name: string
        className: string | null
        count: number
        registration: string
        registrationQuality: number | null
        registrationNotes: string | null
        totalScore: number | null
        totalMax: number | null
        pendingReview: number
        firstSubmissionId: string
      }
    >()
    const registrationRank = (status: string | null | undefined) =>
      status === "failed" ? 0 : status === "pending" ? 1 : 2
    for (const row of rows) {
      const key = `${row.class_name ?? ""}::${row.student_name ?? ""}`
      const existing = map.get(key)
      if (!existing) {
        map.set(key, {
          name: row.student_name || "未命名",
          className: row.class_name ?? null,
          count: 1,
          registration: row.registration_status ?? "pending",
          registrationQuality: row.registration_quality ?? null,
          registrationNotes: row.registration_notes ?? null,
          totalScore: row.total_score ?? null,
          totalMax: row.total_max_score ?? null,
          pendingReview: row.pending_review_count ?? 0,
          firstSubmissionId: row.submission_id,
        })
        continue
      }
      existing.count += 1
      if (
        registrationRank(row.registration_status) <
        registrationRank(existing.registration)
      ) {
        existing.registration = row.registration_status ?? "pending"
        existing.registrationNotes = row.registration_notes ?? null
      }
      if (
        row.registration_quality != null &&
        (existing.registrationQuality == null ||
          row.registration_quality < existing.registrationQuality)
      ) {
        existing.registrationQuality = row.registration_quality
      }
      if (row.total_score != null) {
        existing.totalScore = (existing.totalScore ?? 0) + row.total_score
        existing.totalMax =
          (existing.totalMax ?? 0) + (row.total_max_score ?? 0)
      }
      existing.pendingReview += row.pending_review_count ?? 0
    }
    return Array.from(map.values())
  }, [scoreSummary.data])
  const create = useMutation({
    mutationFn: () =>
      workflowApi<Run>("/grading/runs", {
        method: "POST",
        body: JSON.stringify({
          exam_id: examId,
        }),
      }),
    onSuccess: (run) => {
      start.mutate(run.id)
      client.invalidateQueries({ queryKey: ["grading-runs", examId] })
    },
  })
  const start = useMutation({
    mutationFn: (id: string) =>
      workflowApi(`/grading/runs/${id}/start`, { method: "POST" }),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["grading-runs", examId] }),
  })
  const latest = runs.data?.data?.[0]
  const reviewQueue = useQuery({
    queryKey: ["grading-review-queue", latest?.id],
    queryFn: () =>
      workflowApi<ReviewItem[]>(`/grading/runs/${latest?.id}/review-queue`),
    enabled: Boolean(latest?.id),
    refetchInterval: latest?.status === "running" ? 3000 : false,
  })
  const reviewCount = reviewQueue.data?.length ?? 0
  const totalPendingReview = (scoreSummary.data?.data ?? []).reduce(
    (total, item) => total + (item.pending_review_count ?? 0),
    0,
  )
  const unfinishedSubmissionCount = (scoreSummary.data?.data ?? []).filter(
    (item) => item.total_score == null,
  ).length
  const batchStillRunning =
    latest?.status === "queued" || latest?.status === "running"
  const readyToPublish =
    Boolean(scoreSummary.data?.data?.length) &&
    totalPendingReview === 0 &&
    unfinishedSubmissionCount === 0 &&
    !batchStillRunning
  const publishScores = useMutation({
    mutationFn: () =>
      workflowApi<ScoreRelease>(`/grading/exams/${examId}/score-releases`, {
        method: "POST",
        body: JSON.stringify({ reason: "教师确认整场成绩" }),
      }),
    onSuccess: (release) => {
      setPublishDialogOpen(false)
      client.setQueryData(["score-release", examId], release)
      showSuccessToast(`成绩第 ${release.version} 版已发布，学生现在可以查看`)
    },
    onError: (error) => {
      showErrorToast(
        error instanceof Error ? error.message : "成绩暂时无法发布，请稍后重试",
      )
    },
  })
  return (
    <div className="flex flex-col gap-6">
      <PageHead
        title="批量批改"
        subtitle="视觉识别、自动评分与分层复核"
        actions={
          <>
            <Button variant="outline" asChild>
              <Link to="/exams/$examId/workbench" params={{ examId }}>
                <PenLine />
                批卷工作台
              </Link>
            </Button>
            <Button variant="ghost" onClick={() => runs.refetch()}>
              <RefreshCw />
              刷新状态
            </Button>
          </>
        }
      />
      <GradingAssignmentsCard examId={examId} />
      <Card className="rounded-2xl shadow-card">
        <CardHeader>
          <CardTitle className="font-medium text-sm">新建批改批次</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="flex items-center justify-end gap-3">
            {unassignedCount > 0 && (
              <span className="text-amber-600 text-sm dark:text-amber-400">
                还有 {unassignedCount} 个班未分配老师，分配后才能开始批改
              </span>
            )}
            <Button
              variant={readyToPublish ? "outline" : "default"}
              className={
                readyToPublish
                  ? "md:w-56"
                  : "bg-gradient-primary text-white hover:opacity-90 md:w-56"
              }
              onClick={() => create.mutate()}
              disabled={create.isPending}
            >
              <Play className="mr-2 size-4" />
              开始批量批改
            </Button>
          </div>
        </CardContent>
      </Card>
      {canPublishScores && (
        <section className="flex flex-col gap-4 rounded-[10px] border border-border bg-card px-5 py-4 shadow-[0_1px_2px_rgba(0,0,0,.04)] sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-full bg-muted">
              {readyToPublish || currentRelease.data ? (
                <CheckCircle2 className="size-5 text-emerald-600" />
              ) : (
                <AlertCircle className="size-5 text-amber-600" />
              )}
            </div>
            <div className="min-w-0">
              <p className="font-medium text-sm">
                {currentRelease.data
                  ? `成绩第 ${currentRelease.data.version} 版已发布`
                  : readyToPublish
                    ? "复核已完成，可以发布成绩"
                    : totalPendingReview > 0
                      ? `还有 ${totalPendingReview} 道题待复核`
                      : batchStillRunning
                        ? "批改完成后再发布成绩"
                        : "全部答卷形成成绩后即可发布"}
              </p>
              <p className="mt-1 text-muted-foreground text-xs">
                {currentRelease.data
                  ? "学生看到的是已发布版本；后续改分不会影响已发布成绩，需再次确认发布。"
                  : "发布后学生才能查看成绩；未发布的建议结果仅老师可见。"}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {totalPendingReview > 0 && (
              <Button variant="outline" size="sm" asChild>
                <Link
                  to="/exams/$examId/workbench"
                  params={{ examId }}
                  search={{ filter: "needs_review" }}
                >
                  去复核
                </Link>
              </Button>
            )}
            <Button
              size="sm"
              className="bg-primary text-primary-foreground hover:bg-primary/90"
              disabled={!readyToPublish || publishScores.isPending}
              onClick={() => setPublishDialogOpen(true)}
            >
              <Send />
              {currentRelease.data ? "发布新版本" : "确认并发布成绩"}
            </Button>
          </div>
        </section>
      )}
      <Card className="rounded-2xl shadow-card">
        <CardHeader>
          <CardTitle className="font-medium text-sm">
            学生答卷（{mergedStudents.length} 人
            {(scoreSummary.data?.data?.length ?? 0) > mergedStudents.length
              ? ` · ${scoreSummary.data?.data?.length} 份`
              : ""}
            ）
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!scoreSummary.data?.data?.length ? (
            <EmptyState
              className="border-0 py-10"
              title="还没有学生答卷"
              description="请先在导入中心上传学生答卷照片，再发起批量批改"
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>学生</TableHead>
                  <TableHead>班级</TableHead>
                  <TableHead>配准</TableHead>
                  <TableHead>得分</TableHead>
                  <TableHead>待复核</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {mergedStudents.map((student) => {
                  const registration =
                    registrationTags[student.registration] ??
                    pendingRegistrationTag
                  return (
                    <TableRow key={`${student.className}-${student.name}`}>
                      <TableCell className="font-medium">
                        {student.name}
                        {student.count > 1 && (
                          <span className="ml-2 text-muted-foreground text-xs font-normal">
                            {student.count} 份
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {student.className || "未分班"}
                      </TableCell>
                      <TableCell>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span className="inline-flex items-center gap-1.5">
                              <Tag variant={registration.variant}>
                                {registration.label}
                              </Tag>
                              {student.registrationQuality != null && (
                                <span className="text-muted-foreground text-xs tabular-nums">
                                  {Math.round(
                                    student.registrationQuality * 100,
                                  )}
                                  %
                                </span>
                              )}
                            </span>
                          </TooltipTrigger>
                          {student.registrationNotes && (
                            <TooltipContent>
                              <p className="max-w-xs text-xs">
                                {formatRegistrationNotes(
                                  student.registrationNotes,
                                )}
                              </p>
                            </TooltipContent>
                          )}
                        </Tooltip>
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {student.totalScore != null
                          ? `${student.totalScore} / ${student.totalMax ?? "--"}`
                          : "未批改"}
                      </TableCell>
                      <TableCell>
                        {student.pendingReview > 0 ? (
                          <Tag variant="amber">{student.pendingReview} 题</Tag>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="sm" asChild>
                          <Link
                            to="/exams/$examId/workbench"
                            params={{ examId }}
                            search={{ student: student.name }}
                          >
                            复核
                          </Link>
                        </Button>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      {latest && (
        <Card className="rounded-2xl shadow-card">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="font-medium text-sm">最近批次</CardTitle>
            <Tag
              variant={
                (gradingRunStatusTags[latest.status] ?? { variant: "indigo" })
                  .variant
              }
            >
              {gradingRunStatusTags[latest.status]?.label ?? latest.status}
            </Tag>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-8">
              <div>
                <span className="text-muted-foreground">进度</span>
                <p>
                  {latest.completed_items} / {latest.total_items} 题块
                </p>
                <ProgressBar
                  slim
                  striped={latest.status === "running"}
                  value={
                    latest.total_items > 0
                      ? (latest.completed_items / latest.total_items) * 100
                      : 0
                  }
                  className="mt-1.5"
                />
              </div>
              <div>
                <span className="text-muted-foreground">已提取</span>
                <p>{latest.extracted_items}</p>
              </div>
              <div>
                <span className="text-muted-foreground">处理结果</span>
                <p>
                  客观题 {latest.objective_items} / 主观题{" "}
                  {latest.subjective_items}
                </p>
              </div>
              <div>
                <span className="text-muted-foreground">自动检查</span>
                <p>
                  {latest.average_confidence == null
                    ? "--"
                    : latest.average_confidence < 0.8
                      ? "部分题目需复核"
                      : "未发现集中异常"}
                </p>
              </div>
              <div>
                <span className="text-muted-foreground">待复核</span>
                <p>{latest.review_count}</p>
              </div>
              <div>
                <span className="text-muted-foreground">失败</span>
                <p>{latest.failed_count}</p>
              </div>
              <div>
                <span className="text-muted-foreground">处理状态</span>
                <p>{latest.throttle_count ? "服务繁忙，已自动调节" : "正常"}</p>
              </div>
              <div>
                <span className="text-muted-foreground">提取耗时</span>
                <p>{latest.timing?.ocr_ms ?? latest.timing?.ocrMs ?? 0} ms</p>
              </div>
              <div>
                <span className="text-muted-foreground">总耗时</span>
                <p>
                  {latest.timing?.total_elapsed_ms ??
                    latest.timing?.totalElapsedMs ??
                    0}{" "}
                  ms
                </p>
              </div>
            </div>
            <div className="mt-4 flex items-center gap-2 text-muted-foreground text-sm">
              {latest.status === "running" && (
                <Clock3 className="size-4 animate-pulse text-sky-500" />
              )}{" "}
              {latest.status.startsWith("completed") && (
                <CheckCircle2 className="size-4 text-emerald-500" />
              )}
              <span>
                {latest.status === "running"
                  ? "正在识别和评分，页面会自动刷新"
                  : "批次处理完成后可进入答卷复核"}
              </span>
            </div>
            {latest.timing?.fallback_used && (
              <div className="mt-3 border-amber-200 border-t pt-3 text-amber-700 text-sm">
                主通道暂时不可用，本批次已自动切换备用通道继续处理
              </div>
            )}
          </CardContent>
        </Card>
      )}
      {latest && (
        <Card className="rounded-2xl shadow-card">
          <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
            <CardTitle className="font-medium text-sm">分层复核队列</CardTitle>
            <div className="flex items-center gap-2">
              {reviewCount > 0 && (
                <Button
                  size="sm"
                  className="bg-gradient-primary text-white hover:opacity-90"
                  asChild
                >
                  <Link
                    to="/exams/$examId/workbench"
                    params={{ examId }}
                    search={{ filter: "needs_review" }}
                  >
                    继续复核 {reviewCount} 题
                  </Link>
                </Button>
              )}
              <Button variant="ghost" size="sm" asChild>
                <Link to="/exams/$examId/workbench" params={{ examId }}>
                  查看全部答卷
                </Link>
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {reviewCount === 0 ? (
              <EmptyState
                className="border-0 py-10"
                title="没有需要复核的题目"
              />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>优先级</TableHead>
                    <TableHead>学生</TableHead>
                    <TableHead>题目</TableHead>
                    <TableHead>原因</TableHead>
                    <TableHead>建议得分</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {reviewQueue.data?.map((item) => (
                    <TableRow key={`${item.submission_id}-${item.label}`}>
                      <TableCell>
                        <Tag variant={item.priority >= 100 ? "red" : "indigo"}>
                          {item.priority >= 100 ? "高" : "普通"}
                        </Tag>
                      </TableCell>
                      <TableCell>
                        {item.student_name ||
                          item.student_identifier ||
                          "未识别"}
                      </TableCell>
                      <TableCell>{item.label || "整卷"}</TableCell>
                      <TableCell className="text-amber-600 dark:text-amber-400">
                        {reviewReasonText(item)}
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {item.score ?? "--"} / {item.max_score ?? "--"}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center justify-end gap-3">
                          <Button variant="outline" size="sm" asChild>
                            <Link
                              to="/exams/$examId/workbench"
                              params={{ examId }}
                              search={{
                                student: item.student_name ?? "",
                                filter: "needs_review",
                              }}
                            >
                              进入复核
                            </Link>
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}
      <Dialog open={publishDialogOpen} onOpenChange={setPublishDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>确认发布整场成绩？</DialogTitle>
            <DialogDescription>
              发布后，学生将立即看到本次确认的分数和评语。系统会保存不可变版本，后续改分需要再次发布。
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-[10px] border bg-muted/40 px-4 py-3 text-sm">
            本次将发布 {mergedStudents.length} 名学生的成绩
            {currentRelease.data
              ? `，生成第 ${currentRelease.data.version + 1} 版`
              : ""}
            。
          </div>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline">取消</Button>
            </DialogClose>
            <Button
              className="bg-primary text-primary-foreground hover:bg-primary/90"
              disabled={publishScores.isPending}
              onClick={() => publishScores.mutate()}
            >
              {publishScores.isPending ? "正在发布…" : "确认发布"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
