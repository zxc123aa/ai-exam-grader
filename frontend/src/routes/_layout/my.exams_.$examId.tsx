import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowLeft, BookOpenCheck, Printer, UserRound } from "lucide-react"
import { useMemo } from "react"
import { ApiError, StudentsService } from "@/client"
import { AvatarGradient } from "@/components/Common/AvatarGradient"
import { EmptyState } from "@/components/Common/EmptyState"
import { PageHead } from "@/components/Common/PageHead"
import { ProgressBar, type ProgressTone } from "@/components/Common/ProgressBar"
import { Tag } from "@/components/Common/Tag"
import {
  buildSummaryLine,
  formatScore,
  type ReportQuestionItem,
  rateColor,
  scoreRate,
  sortQuestionsByLabel,
} from "@/components/Report/report-utils"
import { WrongQuestionsSection } from "@/components/Report/WrongQuestionsSection"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"

export const Route = createFileRoute("/_layout/my/exams_/$examId")({
  component: MyExamReportPage,
  head: () => ({ meta: [{ title: "个人成绩报告 - 点凡阅卷" }] }),
})

/** 学习建议：调用后端按本场考试错题实时生成的建议（LLM），会话内只取一次。 */
function LearningAdviceSection({ examId }: { examId: string }) {
  const query = useQuery({
    queryKey: ["my-exam-learning-advice", examId],
    queryFn: () => StudentsService.readMyLearningAdvice({ examId }),
    staleTime: Number.POSITIVE_INFINITY,
    retry: 1,
  })

  if (query.isPending) {
    return (
      <section className="border-t py-6">
        <h4 className="mb-4 font-semibold text-sm">学习建议</h4>
        <div className="flex flex-col gap-2">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      </section>
    )
  }

  if (query.isError) {
    return (
      <section className="border-t py-6">
        <h4 className="mb-4 font-semibold text-sm">学习建议</h4>
        <p className="text-muted-foreground text-sm">
          学习建议暂时生成失败，稍后可刷新重试。
        </p>
      </section>
    )
  }

  const advice = query.data
  if (!advice?.has_data) {
    return (
      <section className="border-t py-6">
        <h4 className="mb-4 font-semibold text-sm">学习建议</h4>
        <p className="text-muted-foreground text-sm leading-7">
          本次考试没有错题，保持当前学习节奏即可。
        </p>
      </section>
    )
  }

  return (
    <section className="border-t py-6">
      <h4 className="mb-4 font-semibold text-sm">学习建议</h4>
      {advice.overall && (
        <p className="text-muted-foreground text-sm leading-7">
          {advice.overall}
        </p>
      )}
      {(advice.focus_points ?? []).length > 0 && (
        <ul className="mt-3 flex flex-col gap-2">
          {(advice.focus_points ?? []).map((point) => (
            <li key={point.knowledge_point} className="text-sm leading-7">
              <span className="font-medium">{point.knowledge_point}</span>
              <span className="text-muted-foreground">
                （错 {point.times} 次）：{point.advice}
              </span>
              <Link
                to="/my/wrongbook-sheet"
                search={{
                  mode: "variants",
                  kps: point.knowledge_point,
                  range: "all",
                  limit: 10,
                }}
                className="ml-2 whitespace-nowrap text-primary text-xs hover:underline"
              >
                出变式练习 →
              </Link>
            </li>
          ))}
        </ul>
      )}
      {(advice.weekly_plan ?? []).length > 0 && (
        <ol className="mt-3 list-decimal pl-5 text-muted-foreground text-sm leading-7">
          {(advice.weekly_plan ?? []).map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      )}
    </section>
  )
}

function MyExamReportPage() {
  const { examId } = Route.useParams()
  const query = useQuery({
    queryKey: ["my-exam-report", examId],
    queryFn: () => StudentsService.readMyExamReport({ examId }),
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 3,
  })

  const today = useMemo(
    () =>
      new Date().toLocaleDateString("zh-CN", {
        year: "numeric",
        month: "long",
        day: "numeric",
      }),
    [],
  )

  const isUnbound =
    query.error instanceof ApiError && query.error.status === 404

  if (query.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="mx-auto h-[1100px] w-full max-w-[820px]" />
      </div>
    )
  }

  if (isUnbound) {
    return (
      <EmptyState
        icon={UserRound}
        title="账号未绑定学生档案"
        description="请联系老师将你的账号绑定到班级学生档案后查看成绩"
      />
    )
  }

  if (query.isError || !query.data) {
    return (
      <p className="text-destructive text-sm">
        成绩报告加载失败：{String(query.error)}
      </p>
    )
  }

  const report = query.data
  // 知识点与答题图来自错题本快照，不需要考试接口权限
  const questions = sortQuestionsByLabel(
    (report.questions ?? []).map(
      (question): ReportQuestionItem => ({
        label: question.label,
        score: question.score ?? null,
        maxScore: question.max_score ?? null,
        source: question.score_source ?? null,
        comment: question.comment || question.suggested_comment || null,
        entryId: question.entry_id ?? null,
        hasImage: question.has_image ?? false,
      }),
    ),
  )
  const knowledgeByLabel = new Map(
    (report.questions ?? [])
      .filter((question) => (question.knowledge_point_names ?? []).length > 0)
      .map((question) => [
        question.label,
        (question.knowledge_point_names ?? []).join("、"),
      ]),
  )
  const scored = questions.filter((question) => scoreRate(question) != null)
  const fullCount = scored.filter(
    (question) => scoreRate(question) === 100,
  ).length
  const zeroCount = scored.filter(
    (question) => scoreRate(question) === 0,
  ).length
  const partialCount = scored.length - fullCount - zeroCount
  const bands: Array<{ label: string; count: number; tone: ProgressTone }> = [
    { label: "满分题", count: fullCount, tone: "mint" },
    { label: "部分得分", count: partialCount, tone: "amber" },
    { label: "零分题", count: zeroCount, tone: "pink" },
  ]
  const summaryLine = buildSummaryLine(questions, knowledgeByLabel)

  return (
    <div className="flex flex-col gap-6">
      <div className="print:hidden">
        <Link
          to="/my/exams"
          className="mb-2 inline-flex items-center gap-1 text-muted-foreground text-sm hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          返回我的成绩
        </Link>
        <PageHead
          title={report.title}
          subtitle="个人成绩报告 · 可打印或导出 PDF"
          actions={
            <Button variant="ghost" onClick={() => window.print()}>
              <Printer />
              打印
            </Button>
          }
        />
      </div>

      {/* A4 报告卡片 */}
      <div className="mx-auto w-full max-w-[820px] rounded-2xl bg-card p-10 shadow-card-lg print:max-w-none print:rounded-none print:p-0 print:shadow-none">
        {/* 品牌行 */}
        <div className="flex items-center gap-2 border-b pb-5">
          <span className="flex size-8 items-center justify-center rounded-lg bg-gradient-primary text-white">
            <BookOpenCheck className="size-4" />
          </span>
          <span className="font-semibold">点凡阅卷 · 个人成绩报告</span>
          <span className="ml-auto text-muted-foreground text-xs">
            {report.title}
          </span>
        </div>

        {/* 学生头 */}
        <div className="flex flex-wrap items-center gap-4 py-6">
          <AvatarGradient name={report.student_name ?? "我"} size={52} />
          <div className="min-w-0">
            <h3 className="font-bold text-xl">{report.student_name ?? "--"}</h3>
            <p className="mt-0.5 text-muted-foreground text-xs">
              {[report.class_name, report.subject, report.grade_level]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </div>
          <div className="ml-auto text-right">
            <div className="flex items-baseline justify-end gap-1.5">
              <span className="font-bold text-4xl tracking-tight">
                {formatScore(report.total_score)}
              </span>
              <span className="text-muted-foreground text-sm">
                / {formatScore(report.total_max_score)} 分
              </span>
            </div>
            <p className="mt-1 text-muted-foreground text-xs">
              {report.class_rank != null
                ? `班级排名 ${report.class_rank} / ${report.class_size ?? "--"}`
                : "暂无排名"}
            </p>
          </div>
          {summaryLine && (
            <p className="w-full text-muted-foreground text-sm">
              {summaryLine}
            </p>
          )}
        </div>

        {/* 得分分布 */}
        <section className="border-t py-6">
          <h4 className="mb-4 font-semibold text-sm">得分分布</h4>
          <div className="flex flex-col gap-3">
            {bands.map((band) => (
              <div key={band.label} className="flex items-center gap-3">
                <span className="w-16 shrink-0 text-muted-foreground text-xs">
                  {band.label}
                </span>
                <ProgressBar
                  tone={band.tone}
                  value={
                    scored.length > 0 ? (band.count / scored.length) * 100 : 0
                  }
                />
                <span className="w-20 shrink-0 text-right text-xs">
                  {band.count} 题
                  <span className="text-muted-foreground">
                    {scored.length > 0
                      ? ` · ${Math.round((band.count / scored.length) * 100)}%`
                      : ""}
                  </span>
                </span>
              </div>
            ))}
          </div>
        </section>

        {/* 错题回顾：得分率 <60% 的题，含评语/正确思路 */}
        <WrongQuestionsSection
          examId={examId}
          questions={questions}
          knowledgeByLabel={knowledgeByLabel}
        />

        {/* 学习建议 */}
        <LearningAdviceSection examId={examId} />

        {/* 逐题明细 */}
        <section className="border-t py-6">
          <h4 className="mb-4 font-semibold text-sm">逐题得分与评语</h4>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-20">题号</TableHead>
                <TableHead className="w-28">得分</TableHead>
                <TableHead>评语</TableHead>
                <TableHead className="w-20 text-right">标记</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {questions.map((question) => {
                const rate = scoreRate(question)
                return (
                  <TableRow key={question.label}>
                    <TableCell className="font-medium">
                      {question.label}
                    </TableCell>
                    <TableCell>
                      <span className={cn("font-semibold", rateColor(rate))}>
                        {formatScore(question.score)}
                      </span>
                      <span className="text-muted-foreground">
                        {" "}
                        / {formatScore(question.maxScore)}
                      </span>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {question.comment ?? "--"}
                    </TableCell>
                    <TableCell className="text-right">
                      {question.source === "final" && (
                        <Tag variant="pink">师改</Tag>
                      )}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </section>

        {/* 页脚 */}
        <p className="border-t pt-5 text-muted-foreground text-xs">
          本报告由点凡阅卷 自动生成 · {today}
        </p>
      </div>
    </div>
  )
}
