import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { CheckCircle2, Clock3, Play, RefreshCw } from "lucide-react"
import { useMemo, useState } from "react"

import { ExamsService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { workflowApi } from "@/lib/workflow-api"

export const Route = createFileRoute("/_layout/exams_/$examId/grading")({
  component: GradingWorkspace,
  head: () => ({ meta: [{ title: "批量批改 - 智阅卷" }] }),
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
const gradingRunStatusLabels: Record<string, string> = {
  queued: "排队中",
  running: "批改中",
  completed: "已完成",
  completed_with_errors: "已完成（部分失败）",
  failed: "失败",
}
const providerModels: Record<string, string[]> = {
  pomoai: [
    "gpt-5.6-sol",
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-opus-4-6",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "grok-4.5",
    "gemini-3.5-flash",
  ],
  fluxnode_gemini: ["gemini-3.5-flash"],
  fluxnode_grok: ["grok-4.5"],
  kimi: [
    "kimi-k2.7-code",
    "kimi-k2.7-code-highspeed",
    "kimi-k2.6",
    "kimi-k2.5",
  ],
}
function GradingWorkspace() {
  const { examId } = Route.useParams()
  const client = useQueryClient()
  const [provider, setProvider] = useState("pomoai")
  const [model, setModel] = useState("gpt-5.6-sol")
  const [threshold, setThreshold] = useState("0.8")
  const [maxConcurrency, setMaxConcurrency] = useState("8")
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
          vision_provider: "fluxnode_gemini",
          vision_model: "gemini-3.5-flash",
          provider,
          model,
          review_threshold: Number(threshold),
          max_concurrency: Number(maxConcurrency),
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
  return (
    <div className="flex flex-col gap-6">
      <p className="text-muted-foreground">视觉识别、自动评分与分层复核</p>
      <Card>
        <CardHeader>
          <CardTitle>新建批改批次</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-6">
          <div className="grid gap-2">
            <Label>视觉提取</Label>
            <div className="flex h-9 items-center rounded-md border bg-muted/40 px-3 text-sm">
              FluxNode · Gemini 3.5 Flash
            </div>
          </div>
          <div className="grid gap-2">
            <Label>判题提供者</Label>
            <select
              className="h-9 rounded-md border bg-background px-3"
              value={provider}
              onChange={(event) => {
                const nextProvider = event.target.value
                setProvider(nextProvider)
                setModel(providerModels[nextProvider][0])
              }}
            >
              <option value="pomoai">PomoAI</option>
              <option value="fluxnode_gemini">FluxNode · Gemini</option>
              <option value="fluxnode_grok">FluxNode · Grok</option>
              <option value="kimi">Kimi Coding</option>
            </select>
          </div>
          <div className="grid gap-2">
            <Label>判题模型</Label>
            <select
              className="h-9 rounded-md border bg-background px-3"
              value={model}
              onChange={(event) => setModel(event.target.value)}
            >
              {providerModels[provider].map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          <div className="grid gap-2">
            <Label>复核阈值</Label>
            <Input
              type="number"
              min="0"
              max="1"
              step="0.05"
              value={threshold}
              onChange={(event) => setThreshold(event.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label>最大并发</Label>
            <Input
              type="number"
              min="1"
              max="8"
              value={maxConcurrency}
              onChange={(event) => setMaxConcurrency(event.target.value)}
            />
          </div>
          <div className="flex items-end">
            <Button
              className="w-full"
              onClick={() => create.mutate()}
              disabled={create.isPending}
            >
              <Play className="mr-2 size-4" />
              开始批量批改
            </Button>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>
            学生答卷（{mergedStudents.length} 人
            {(scoreSummary.data?.data?.length ?? 0) > mergedStudents.length
              ? ` · ${scoreSummary.data?.data?.length} 份`
              : ""}
            ）
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!scoreSummary.data?.data?.length ? (
            <p className="text-muted-foreground text-sm">
              还没有学生答卷，请先在导入中心上传。
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground text-xs">
                    <th className="py-2 pr-4 font-medium">学生</th>
                    <th className="py-2 pr-4 font-medium">班级</th>
                    <th className="py-2 pr-4 font-medium">配准</th>
                    <th className="py-2 pr-4 font-medium">得分</th>
                    <th className="py-2 pr-4 font-medium">待复核</th>
                    <th className="py-2 font-medium" />
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {mergedStudents.map((student) => (
                    <tr key={`${student.className}-${student.name}`}>
                      <td className="py-2 pr-4 font-medium">
                        {student.name}
                        {student.count > 1 && (
                          <span className="ml-2 text-muted-foreground text-xs font-normal">
                            {student.count} 份
                          </span>
                        )}
                      </td>
                      <td className="py-2 pr-4 text-muted-foreground">
                        {student.className || "未分班"}
                      </td>
                      <td className="py-2 pr-4">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span className="inline-flex items-center gap-1.5">
                              <Badge
                                variant={
                                  student.registration === "failed"
                                    ? "destructive"
                                    : "secondary"
                                }
                              >
                                {student.registration === "failed"
                                  ? "配准失败"
                                  : student.registration === "manual_confirmed"
                                    ? "人工配准"
                                    : student.registration === "auto_confirmed"
                                      ? "自动配准"
                                      : "待配准"}
                              </Badge>
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
                      </td>
                      <td className="py-2 pr-4 tabular-nums">
                        {student.totalScore != null
                          ? `${student.totalScore} / ${student.totalMax ?? "--"}`
                          : "未批改"}
                      </td>
                      <td className="py-2 pr-4">
                        {student.pendingReview > 0 ? (
                          <Badge variant="outline">
                            {student.pendingReview} 题
                          </Badge>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="py-2 text-right">
                        <Button variant="ghost" size="sm" asChild>
                          <Link
                            to="/exams/$examId/submissions/$submissionId/review"
                            params={{
                              examId,
                              submissionId: student.firstSubmissionId,
                            }}
                          >
                            复核
                          </Link>
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
      {latest && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>最近批次</CardTitle>
            <Badge
              variant={
                latest.status === "failed"
                  ? "destructive"
                  : latest.status === "completed_with_errors"
                    ? "outline"
                    : "secondary"
              }
            >
              {gradingRunStatusLabels[latest.status] ?? latest.status}
            </Badge>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-8">
              <div>
                <span className="text-muted-foreground">模型</span>
                <p>
                  {latest.provider} / {latest.model}
                </p>
              </div>
              <div>
                <span className="text-muted-foreground">进度</span>
                <p>
                  {latest.completed_items} / {latest.total_items} 题块
                </p>
              </div>
              <div>
                <span className="text-muted-foreground">已提取</span>
                <p>{latest.extracted_items}</p>
              </div>
              <div>
                <span className="text-muted-foreground">判分方式</span>
                <p>
                  规则 {latest.objective_items} / GPT {latest.subjective_items}
                </p>
              </div>
              <div>
                <span className="text-muted-foreground">平均置信度</span>
                <p>
                  {latest.average_confidence == null
                    ? "--"
                    : `${(latest.average_confidence * 100).toFixed(1)}%`}
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
                <span className="text-muted-foreground">并发 / 降速</span>
                <p>
                  {latest.current_concurrency} / {latest.throttle_count}
                </p>
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
            <div className="mt-4 flex gap-2">
              {latest.status === "running" && (
                <Clock3 className="size-4 animate-pulse" />
              )}{" "}
              {latest.status.startsWith("completed") && (
                <CheckCircle2 className="size-4 text-green-600" />
              )}
              <span>
                {latest.status === "running"
                  ? "正在识别和评分，页面会自动刷新"
                  : "批次处理完成后可进入答卷复核"}
              </span>
              <Button variant="ghost" size="sm" onClick={() => runs.refetch()}>
                <RefreshCw className="mr-1 size-4" />
                刷新
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
      {latest && (reviewQueue.data?.length ?? 0) > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>分层复核队列</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-2">优先级</th>
                  <th>学生</th>
                  <th>题目</th>
                  <th>风险</th>
                  <th>模型得分</th>
                  <th>置信度</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {reviewQueue.data?.map((item) => (
                  <tr
                    className="border-b last:border-0"
                    key={`${item.submission_id}-${item.label}`}
                  >
                    <td className="py-3">
                      <Badge
                        variant={
                          item.priority >= 100 ? "destructive" : "secondary"
                        }
                      >
                        {item.priority >= 100 ? "高" : "普通"}
                      </Badge>
                    </td>
                    <td>
                      {item.student_name || item.student_identifier || "未识别"}
                    </td>
                    <td>{item.label || "整卷"}</td>
                    <td>{item.risk}</td>
                    <td>
                      {item.score ?? "--"} / {item.max_score ?? "--"}
                    </td>
                    <td>
                      {item.confidence == null
                        ? "--"
                        : `${(item.confidence * 100).toFixed(1)}%`}
                    </td>
                    <td className="text-right">
                      <Button variant="outline" size="sm" asChild>
                        <Link
                          to="/exams/$examId/submissions/$submissionId/review"
                          params={{ examId, submissionId: item.submission_id }}
                        >
                          进入复核
                        </Link>
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
