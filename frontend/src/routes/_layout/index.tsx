import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import type { LucideIcon } from "lucide-react"
import {
  BarChart3,
  CheckCheck,
  CheckCircle2,
  ChevronRight,
  Clock,
  FileText,
  NotebookPen,
  PenLine,
  Upload,
  Zap,
} from "lucide-react"
import { useMemo } from "react"

import {
  type ExamScoreSummaryRow,
  type ExamStatus,
  ExamsService,
} from "@/client"
import { EmptyState } from "@/components/Common/EmptyState"
import { PageHead } from "@/components/Common/PageHead"
import { ProgressBar } from "@/components/Common/ProgressBar"
import { StatCard, type StatTone } from "@/components/Common/StatCard"
import { Tag, type TagVariant } from "@/components/Common/Tag"
import { LineChart } from "@/components/charts/LineChart"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import useAuth from "@/hooks/useAuth"
import { useCurrentExam } from "@/hooks/useCurrentExam"
import { workflowApi } from "@/lib/workflow-api"

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({
    meta: [{ title: "工作台 - 点凡阅卷" }],
  }),
})

/** 批卷任务（/api/v1/grading/runs 返回的 Run） */
type GradingRun = {
  id: string
  status: string
  total_submissions: number
  completed_count: number
  failed_count: number
  created_at?: string | null
}

const RUN_STATUS: Record<string, { label: string; variant: TagVariant }> = {
  completed: { label: "已完成", variant: "mint" },
  completed_with_errors: { label: "部分失败", variant: "amber" },
  running: { label: "批改中", variant: "sky" },
  queued: { label: "排队中", variant: "indigo" },
  failed: { label: "失败", variant: "red" },
}

const EXAM_STATUS_LABELS: Record<ExamStatus, string> = {
  draft: "草稿",
  active: "进行中",
  archived: "已归档",
}

/** 按当前小时给出问候语 */
function greeting() {
  const h = new Date().getHours()
  if (h >= 5 && h < 9) return "早上好"
  if (h >= 9 && h < 12) return "上午好"
  if (h >= 12 && h < 18) return "下午好"
  return "晚上好"
}

function formatTime(value?: string | null) {
  if (!value) return "—"
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return "—"
  return d.toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

/** 快捷操作配置（对齐原型 quick-grid） */
type QuickAction = {
  icon: LucideIcon
  tone: StatTone
  title: string
  description: string
} & (
  | { to: "/exams" | "/compose"; needsExam?: false }
  | {
      to: "/exams/$examId/workbench" | "/exams/$examId/report"
      needsExam: true
    }
)

const QUICK_ACTIONS: QuickAction[] = [
  {
    icon: Upload,
    tone: "indigo",
    title: "导入新试卷",
    description: "扫描件 / 答案批量上传",
    to: "/exams",
  },
  {
    icon: PenLine,
    tone: "mint",
    title: "开始智能批卷",
    description: "自动批改 + 人工复核",
    to: "/exams/$examId/workbench",
    needsExam: true,
  },
  {
    icon: FileText,
    tone: "amber",
    title: "生成改卷报告",
    description: "逐题得分与学习建议",
    to: "/exams/$examId/report",
    needsExam: true,
  },
  {
    icon: NotebookPen,
    tone: "pink",
    title: "针对薄弱点组卷",
    description: "错题推荐一键生成",
    to: "/compose",
  },
]

const QUICK_TONE_CLASSES: Record<StatTone, string> = {
  // 快捷操作图标块统一中性色（视觉规范：不每个入口一种颜色）
  indigo: "bg-secondary text-muted-foreground",
  violet: "bg-secondary text-muted-foreground",
  mint: "bg-secondary text-muted-foreground",
  amber: "bg-secondary text-muted-foreground",
  sky: "bg-secondary text-muted-foreground",
  pink: "bg-secondary text-muted-foreground",
}

/** 当前考试的成绩统计：待复核 / 完成率 / 平均分 / AI 采纳率 */
function DashboardStats({ examId }: { examId: string }) {
  const summary = useQuery({
    queryKey: ["exam-score-summary", examId],
    queryFn: () => ExamsService.readExamScoresSummary({ examId }),
  })
  const submissions = useQuery({
    queryKey: ["exam-submissions", examId],
    queryFn: () => ExamsService.readStudentSubmissions({ examId }),
  })

  const stats = useMemo(() => {
    const rows = summary.data?.data ?? []
    // 一个学生可能有多条 submission，按 班级+姓名 归并为学生粒度
    const pendingStudents = new Map<string, number>()
    for (const row of rows) {
      const key = `${row.class_name ?? ""}|${row.student_name ?? ""}`
      pendingStudents.set(
        key,
        (pendingStudents.get(key) ?? 0) + (row.pending_review_count ?? 0),
      )
    }
    const pendingCount = [...pendingStudents.values()].filter(
      (n) => n > 0,
    ).length

    const totalStudents = new Set(
      (submissions.data?.data ?? []).map(
        (s) => `${s.class_name ?? ""}|${s.student_name ?? ""}`,
      ),
    ).size
    const gradedCount = rows.length
    const completion =
      totalStudents > 0 ? Math.round((gradedCount / totalStudents) * 100) : 0

    const scored = rows
      .map((r) => r.total_score)
      .filter((s): s is number => s != null)
    const avg = scored.length
      ? scored.reduce((a, b) => a + b, 0) / scored.length
      : null
    const maxScore = Math.max(0, ...rows.map((r) => r.total_max_score ?? 0))

    const questions = rows.flatMap((r) => r.questions ?? [])
    const aiAdopted = questions.filter(
      (q) => q.score_source === "ai_suggested",
    ).length
    const adoptionRate = questions.length
      ? Math.round((aiAdopted / questions.length) * 100)
      : 0

    return { pendingCount, completion, avg, maxScore, adoptionRate }
  }, [summary.data, submissions.data])

  if (summary.isPending || submissions.isPending) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {["pending", "completion", "average", "adoption"].map((key) => (
          <Skeleton key={key} className="h-40 rounded-2xl" />
        ))}
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard
        icon={Clock}
        tone="amber"
        value={stats.pendingCount}
        unit="人"
        label="待复核"
        foot="集中处理需要人工确认的题目"
      />
      <StatCard
        icon={CheckCircle2}
        tone="mint"
        value={stats.completion}
        unit="%"
        label="已批完成率"
        foot="已出分学生 / 全部学生"
        ring={stats.completion}
      />
      <StatCard
        icon={BarChart3}
        tone="indigo"
        value={stats.avg != null ? stats.avg.toFixed(1) : "—"}
        unit="分"
        label="班级平均分"
        foot={`满分 ${stats.maxScore || "—"}`}
      />
      <StatCard
        icon={CheckCheck}
        tone="violet"
        value={stats.adoptionRate}
        unit="%"
        label="自动批改通过率"
        foot="自动评分被直接采纳占比"
      />
    </div>
  )
}

/** 最近批卷任务列表 */
function RecentRuns({ examId }: { examId: string }) {
  const runs = useQuery({
    queryKey: ["grading-runs", examId],
    queryFn: () =>
      workflowApi<{ data: GradingRun[] }>(`/grading/runs?exam_id=${examId}`),
  })

  const items = runs.data?.data?.slice(0, 5) ?? []

  return (
    <section className="rounded-2xl border bg-card p-5 shadow-card">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="flex items-center gap-2 font-semibold text-sm">
          <Clock className="size-4 text-muted-foreground" />
          最近批卷任务
        </h3>
        <Link
          to="/exams/$examId/grading"
          params={{ examId }}
          className="text-muted-foreground text-xs hover:text-foreground"
        >
          查看全部 →
        </Link>
      </div>
      {runs.isPending ? (
        <div className="flex flex-col gap-3">
          {["r1", "r2", "r3"].map((key) => (
            <Skeleton key={key} className="h-14 rounded-xl" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          title="暂无批卷任务"
          description="发起一次智能批卷后，任务进度会显示在这里"
          className="border-0 py-10"
        />
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((run) => {
            const total = run.total_submissions || 0
            const pct =
              total > 0 ? Math.round((run.completed_count / total) * 100) : 0
            const status = RUN_STATUS[run.status] ?? {
              label: run.status,
              variant: "indigo" as TagVariant,
            }
            return (
              <li key={run.id}>
                <Link
                  to="/exams/$examId/grading"
                  params={{ examId }}
                  className="flex items-center gap-4 rounded-xl px-3 py-2.5 transition-colors hover:bg-secondary/60"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <p className="truncate font-medium text-sm">
                        批卷任务 #{run.id.slice(0, 8)}
                      </p>
                      <span className="shrink-0 text-muted-foreground text-xs">
                        {formatTime(run.created_at)}
                      </span>
                    </div>
                    <div className="mt-2 flex items-center gap-3">
                      <ProgressBar
                        slim
                        striped={run.status === "running"}
                        value={pct}
                        className="flex-1"
                      />
                      <span className="w-10 shrink-0 text-right font-medium text-sm tabular-nums">
                        {pct}%
                      </span>
                    </div>
                  </div>
                  <Tag variant={status.variant}>{status.label}</Tag>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

/** 班级成绩趋势：每场考试一个点（平均 total_score） */
function ScoreTrend({
  examIds,
  titles,
}: {
  examIds: string[]
  titles: Map<string, string>
}) {
  const trend = useQuery({
    queryKey: ["dashboard-score-trend", examIds.join(",")],
    enabled: examIds.length > 0,
    queryFn: async () => {
      const results = await Promise.all(
        examIds.map(async (examId) => {
          try {
            const res = await ExamsService.readExamScoresSummary({ examId })
            const scores = (res.data ?? [])
              .map((row: ExamScoreSummaryRow) => row.total_score)
              .filter((s): s is number => s != null)
            if (scores.length === 0) return null
            return {
              examId,
              avg: scores.reduce((a, b) => a + b, 0) / scores.length,
            }
          } catch {
            return null
          }
        }),
      )
      return results.filter((r): r is NonNullable<typeof r> => r != null)
    },
  })

  const points = useMemo(() => {
    // exams 按最近排序，趋势图按时间正序展示
    return [...(trend.data ?? [])].reverse().map((p) => {
      const title = titles.get(p.examId) ?? "未命名考试"
      return {
        label: title.length > 6 ? `${title.slice(0, 6)}…` : title,
        avg: Number(p.avg.toFixed(1)),
      }
    })
  }, [trend.data, titles])

  return (
    <section className="rounded-2xl border bg-card p-5 shadow-card">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="flex items-center gap-2 font-semibold text-sm">
          <BarChart3 className="size-4 text-muted-foreground" />
          班级成绩趋势
        </h3>
        <span className="text-muted-foreground text-xs">各场考试 · 平均分</span>
      </div>
      {trend.isPending ? (
        <Skeleton className="h-[260px] rounded-xl" />
      ) : points.length < 2 ? (
        <EmptyState
          icon={BarChart3}
          title="至少 2 场考试出分后展示趋势"
          description="完成更多考试的批改后，这里会展示班级平均分走势"
          className="border-0 py-10"
        />
      ) : (
        <LineChart
          labels={points.map((p) => p.label)}
          series={[
            {
              name: "班级平均",
              data: points.map((p) => p.avg),
              color: "#2E5BFF",
            },
          ]}
          unit=" 分"
          height={260}
        />
      )}
    </section>
  )
}

function Dashboard() {
  const { user } = useAuth()
  const { exams, currentExam, currentExamId } = useCurrentExam()

  const titles = useMemo(
    () => new Map(exams.map((exam) => [exam.id, exam.title])),
    [exams],
  )
  const examIds = useMemo(() => exams.map((exam) => exam.id), [exams])

  const name = user?.full_name || user?.email || "老师"
  const subtitle = currentExam
    ? `${currentExam.title} · ${EXAM_STATUS_LABELS[currentExam.status ?? "draft"]}`
    : "还没有进行中的考试，先创建一场考试吧"

  return (
    <div className="flex flex-col gap-6">
      <PageHead
        title={`${greeting()}，${name}老师`}
        subtitle={subtitle}
        actions={
          currentExamId ? (
            <>
              <Button variant="ghost" asChild>
                <Link
                  to="/exams/$examId/scores"
                  params={{ examId: currentExamId }}
                >
                  <BarChart3 />
                  查看班级分析
                </Link>
              </Button>
              <Button asChild>
                <Link
                  to="/exams/$examId/workbench"
                  params={{ examId: currentExamId }}
                >
                  <Zap />
                  继续批卷
                </Link>
              </Button>
            </>
          ) : (
            <Button asChild>
              <Link to="/exams">
                <Upload />
                去创建考试
              </Link>
            </Button>
          )
        }
      />

      {currentExamId ? (
        <>
          <DashboardStats examId={currentExamId} />
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <RecentRuns examId={currentExamId} />
            <ScoreTrend examIds={examIds} titles={titles} />
          </div>
        </>
      ) : (
        <section
          className="rounded-2xl border bg-card p-6"
          data-testid="first-exam-guide"
        >
          <h2 className="font-semibold">第一场考试，三步就好</h2>
          <ol className="mt-4 grid gap-4 sm:grid-cols-3">
            {[
              ["新建考试", "填考试名称、班级和科目，一分钟的事。"],
              [
                "导入卷子",
                "跟着页面顶部的步骤条走：导入模板卷和学生答卷，系统会自动扫描校正。",
              ],
              [
                "确认后批改",
                "确认识别出的题目和参考答案，点「开始批量批改」，出分后只需复核异常卷。",
              ],
            ].map(([title, description], index) => (
              <li key={title} className="flex gap-3">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary font-semibold text-primary-foreground text-sm">
                  {index + 1}
                </span>
                <div>
                  <div className="font-medium text-sm">{title}</div>
                  <p className="mt-1 text-muted-foreground text-xs leading-5">
                    {description}
                  </p>
                </div>
              </li>
            ))}
          </ol>
          <div className="mt-5">
            <Button asChild>
              <Link to="/exams">
                <Upload />
                新建第一场考试
              </Link>
            </Button>
          </div>
        </section>
      )}

      <section className="rounded-2xl border bg-card p-5 shadow-card">
        <h3 className="mb-4 flex items-center gap-2 font-semibold text-sm">
          <Zap className="size-4 text-muted-foreground" />
          快捷操作
        </h3>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {QUICK_ACTIONS.map((action) => {
            const content = (
              <>
                <span
                  className={`inline-flex size-11 shrink-0 items-center justify-center rounded-xl ${QUICK_TONE_CLASSES[action.tone]}`}
                >
                  <action.icon className="size-5" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block font-medium text-sm">
                    {action.title}
                  </span>
                  <span className="mt-0.5 block text-muted-foreground text-xs">
                    {action.description}
                  </span>
                </span>
                <ChevronRight className="size-4 shrink-0 text-muted-foreground/60" />
              </>
            )
            const className =
              "flex items-center gap-3 rounded-2xl border bg-card p-4 text-left shadow-card transition-all duration-200 hover:-translate-y-0.5 hover:shadow-card-lg"
            if (action.needsExam && currentExamId) {
              return (
                <Link
                  key={action.title}
                  to={action.to}
                  params={{ examId: currentExamId }}
                  className={className}
                >
                  {content}
                </Link>
              )
            }
            if (action.needsExam) {
              return (
                <div key={action.title} className={`${className} opacity-50`}>
                  {content}
                </div>
              )
            }
            return (
              <Link key={action.title} to={action.to} className={className}>
                {content}
              </Link>
            )
          })}
        </div>
      </section>
    </div>
  )
}
