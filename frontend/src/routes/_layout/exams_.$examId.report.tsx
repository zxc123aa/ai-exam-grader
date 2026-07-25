import { useQueries, useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { BookOpenCheck, FileText, Printer } from "lucide-react"
import { useMemo, useState } from "react"
import type { ExamScoreSummaryRow } from "@/client"
import { ExamsService, QuestionAnswerWorkflowService } from "@/client"
import { AvatarGradient } from "@/components/Common/AvatarGradient"
import { EmptyState } from "@/components/Common/EmptyState"
import { PageHead } from "@/components/Common/PageHead"
import { ProgressBar, type ProgressTone } from "@/components/Common/ProgressBar"
import { Tag } from "@/components/Common/Tag"
import { RadarChart } from "@/components/charts/RadarChart"
import {
  buildAdvice,
  buildSummaryLine,
  formatScore,
  type ReportQuestionItem,
  rateColor,
  scoreRate,
  sortQuestionsByLabel,
} from "@/components/Report/report-utils"
import { WrongQuestionsSection } from "@/components/Report/WrongQuestionsSection"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import useAuth from "@/hooks/useAuth"
import { cn } from "@/lib/utils"

export const Route = createFileRoute("/_layout/exams_/$examId/report")({
  component: ExamReportPage,
  head: () => ({ meta: [{ title: "改卷报告 - 点凡阅卷" }] }),
})

const UNASSIGNED_CLASS = "未分班"

type ReportQuestion = {
  label: string
  score: number | null
  maxScore: number | null
  /** summary 归一化口径：final = 教师复核后的最终分（师改），ai_suggested = AI 建议分 */
  source: "final" | "ai_suggested" | null
  /** 取分来源的答卷与标注，用于拉取该题答题裁切图 */
  submissionId: string | null
  annotationId: string | null
}

type ReportStudent = {
  key: string
  className: string
  studentName: string
  studentIdentifier: string | null
  totalScore: number | null
  totalMaxScore: number | null
  questions: Map<string, ReportQuestion>
  submissionIds: string[]
}

/**
 * 与成绩总览页同一合并口径：一个学生可能有多张答卷照片（多条
 * submission），按「班级 + 学生姓名」合并——总分/满分求和，同 label 的题
 * 取 final 优先、其余保留先出现的非空分数；额外收集 submissionIds 用于
 * 拉取逐题 AI 评语（summary 不含评语字段）。
 */
function mergeStudents(rows: ExamScoreSummaryRow[]): ReportStudent[] {
  const map = new Map<string, ReportStudent>()
  for (const row of rows) {
    const className = row.class_name?.trim() || UNASSIGNED_CLASS
    const studentName = row.student_name?.trim() || "未识别"
    const key = `${className}${studentName}`
    let student = map.get(key)
    if (!student) {
      student = {
        key,
        className,
        studentName,
        studentIdentifier: row.student_identifier ?? null,
        totalScore: null,
        totalMaxScore: null,
        questions: new Map(),
        submissionIds: [],
      }
      map.set(key, student)
    }
    if (!student.studentIdentifier && row.student_identifier) {
      student.studentIdentifier = row.student_identifier
    }
    if (row.total_score != null) {
      student.totalScore = (student.totalScore ?? 0) + row.total_score
    }
    if (row.total_max_score != null) {
      student.totalMaxScore = (student.totalMaxScore ?? 0) + row.total_max_score
    }
    for (const question of row.questions ?? []) {
      const source =
        question.score_source === "final" ||
        question.score_source === "ai_suggested"
          ? question.score_source
          : null
      const incoming: ReportQuestion = {
        label: question.label,
        score: question.score ?? null,
        maxScore: question.max_score ?? null,
        source,
        submissionId: row.submission_id,
        annotationId: question.annotation_id ?? null,
      }
      const existing = student.questions.get(question.label)
      if (!existing) {
        student.questions.set(question.label, incoming)
      } else if (existing.source !== "final" && source === "final") {
        student.questions.set(question.label, incoming)
      } else if (existing.score == null && incoming.score != null) {
        student.questions.set(question.label, incoming)
      }
    }
    student.submissionIds.push(row.submission_id)
  }
  return [...map.values()]
}

function sortedQuestions(student: ReportStudent): ReportQuestion[] {
  return sortQuestionsByLabel([...student.questions.values()])
}

function ExamReportPage() {
  const { examId } = Route.useParams()
  const { user } = useAuth()
  const [selectedKey, setSelectedKey] = useState<string | null>(null)

  const exam = useQuery({
    queryKey: ["exam", examId],
    queryFn: () => ExamsService.readExam({ examId }),
  })
  const summary = useQuery({
    queryKey: ["exam-score-summary", examId],
    queryFn: () => ExamsService.readExamScoresSummary({ examId }),
  })
  // 知识点：题目（knowledge_point）经 region_ids 关联到题区，题区 label 与
  // 报告题号一致，从而得到「题号 → 知识点」映射（学生端无此接口权限，仅教师页使用）。
  const examQuestions = useQuery({
    queryKey: ["exam-questions", examId],
    queryFn: () => QuestionAnswerWorkflowService.listExamQuestions({ examId }),
  })
  const examRegions = useQuery({
    queryKey: ["exam-regions", examId],
    queryFn: () => ExamsService.readExamRegions({ examId }),
  })
  const knowledgeByLabel = useMemo(() => {
    const labelByRegionId = new Map(
      (examRegions.data?.data ?? []).map((region) => [region.id, region.label]),
    )
    const map = new Map<string, string>()
    for (const question of examQuestions.data?.data ?? []) {
      if (!question.knowledge_point) continue
      for (const regionId of question.region_ids ?? []) {
        const label = labelByRegionId.get(regionId)
        if (label && !map.has(label)) {
          map.set(label, question.knowledge_point)
        }
      }
    }
    return map
  }, [examQuestions.data, examRegions.data])

  const rows = useMemo(() => summary.data?.data ?? [], [summary.data])
  const students = useMemo(() => mergeStudents(rows), [rows])

  // 排名：合并后有总分的学生按总分降序
  const ranked = useMemo(
    () =>
      students
        .filter((student) => student.totalScore != null)
        .sort((a, b) => (b.totalScore ?? 0) - (a.totalScore ?? 0)),
    [students],
  )

  const selected =
    students.find((student) => student.key === selectedKey) ?? students[0]
  const rank = selected
    ? ranked.findIndex((student) => student.key === selected.key) + 1 || null
    : null

  // 逐题 AI 评语：summary 不含评语，按选中学生的各 submission 拉 annotations
  const annotationQueries = useQueries({
    queries: (selected?.submissionIds ?? []).map((submissionId) => ({
      queryKey: ["submission-annotations", examId, submissionId],
      queryFn: () =>
        ExamsService.readSubmissionAnnotations({ examId, submissionId }),
    })),
  })
  const commentsByLabel = useMemo(() => {
    const map = new Map<string, string>()
    for (const query of annotationQueries) {
      for (const annotation of query.data?.data ?? []) {
        const text = annotation.comment || annotation.suggested_comment
        if (!text) continue
        // 教师复核（human）的评语优先于 AI 建议
        if (!map.has(annotation.label) || annotation.score_source === "human") {
          map.set(annotation.label, text)
        }
      }
    }
    return map
  }, [annotationQueries])

  const today = useMemo(
    () =>
      new Date().toLocaleDateString("zh-CN", {
        year: "numeric",
        month: "long",
        day: "numeric",
      }),
    [],
  )

  if (summary.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="mx-auto h-[1100px] w-full max-w-[820px]" />
      </div>
    )
  }

  if (summary.isError) {
    return (
      <p className="text-destructive text-sm">
        成绩数据加载失败：{String(summary.error)}
      </p>
    )
  }

  if (!selected) {
    return (
      <EmptyState
        icon={FileText}
        title="暂无可生成报告的学生"
        description="还没有批改出分的学生答卷。请先完成批量批改与复核，再回来查看个性化的改卷报告。"
      />
    )
  }

  const questions = sortedQuestions(selected)
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

  // 雷达：暂无知识点维度，过渡方案取前 6 题的逐题得分率（次要位置小图）
  const radarQuestions = scored.slice(0, 6)
  const reportItems: ReportQuestionItem[] = questions.map((question) => ({
    label: question.label,
    score: question.score,
    maxScore: question.maxScore,
    source: question.source,
    comment: commentsByLabel.get(question.label) ?? null,
    submissionId: question.submissionId,
    annotationId: question.annotationId,
  }))
  const summaryLine = buildSummaryLine(questions, knowledgeByLabel)
  const advice = buildAdvice(questions, knowledgeByLabel)

  return (
    <div className="flex flex-col gap-6">
      <PageHead
        className="print:hidden"
        title="改卷报告"
        subtitle="A4 版式 · 可打印或导出 PDF"
        actions={
          <>
            <Select value={selected.key} onValueChange={setSelectedKey}>
              <SelectTrigger className="w-48">
                <SelectValue placeholder="选择学生" />
              </SelectTrigger>
              <SelectContent>
                {students.map((student) => (
                  <SelectItem key={student.key} value={student.key}>
                    {student.studentName}（{student.className}）
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="ghost" onClick={() => window.print()}>
              <Printer />
              打印
            </Button>
          </>
        }
      />

      {/* A4 报告卡片 */}
      <div className="mx-auto w-full max-w-[820px] rounded-2xl bg-card p-10 shadow-card-lg print:max-w-none print:rounded-none print:p-0 print:shadow-none">
        {/* 品牌行 */}
        <div className="flex items-center gap-2 border-b pb-5">
          <span className="flex size-8 items-center justify-center rounded-lg bg-gradient-primary text-white">
            <BookOpenCheck className="size-4" />
          </span>
          <span className="font-semibold">点凡阅卷 · 个性化学情报告</span>
          {exam.data?.title && (
            <span className="ml-auto text-muted-foreground text-xs">
              {exam.data.title}
            </span>
          )}
        </div>

        {/* 学生头 */}
        <div className="flex flex-wrap items-center gap-4 py-6">
          <AvatarGradient name={selected.studentName} size={52} />
          <div className="min-w-0">
            <h3 className="font-bold text-xl">{selected.studentName}</h3>
            <p className="mt-0.5 text-muted-foreground text-xs">
              {selected.className}
              {selected.studentIdentifier &&
                ` · 学号 ${selected.studentIdentifier}`}
              {exam.data?.title && ` · ${exam.data.title}`}
            </p>
          </div>
          <div className="ml-auto text-right">
            <div className="flex items-baseline justify-end gap-1.5">
              <span className="font-bold text-4xl tracking-tight">
                {formatScore(selected.totalScore)}
              </span>
              <span className="text-muted-foreground text-sm">
                / {formatScore(selected.totalMaxScore)} 分
              </span>
            </div>
            <p className="mt-1 text-muted-foreground text-xs">
              {rank != null
                ? `班级排名 ${rank} / ${ranked.length}`
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

        {/* 错题回顾：得分率 <60% 的题，含答题裁切图与评语 */}
        <WrongQuestionsSection
          examId={examId}
          questions={reportItems}
          knowledgeByLabel={knowledgeByLabel}
        />

        {/* 学习建议为主，雷达缩小放次要位置 */}
        <div className="grid gap-6 border-t py-6 md:grid-cols-[1fr_auto]">
          <section>
            <h4 className="mb-4 font-semibold text-sm">学习建议</h4>
            <p className="text-muted-foreground text-sm leading-7">{advice}</p>
          </section>
          {radarQuestions.length >= 3 && (
            <section className="w-[180px]">
              <h4 className="mb-4 font-semibold text-muted-foreground text-xs">
                逐题得分率雷达
              </h4>
              <RadarChart
                labels={radarQuestions.map((question) => question.label)}
                values={radarQuestions.map(
                  (question) => scoreRate(question) ?? 0,
                )}
                size={180}
              />
            </section>
          )}
        </div>

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
                      {commentsByLabel.get(question.label) ?? "--"}
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
          本报告由点凡阅卷 自动生成，任课教师{" "}
          {user?.full_name || user?.email || "--"} 审核 · {today}
        </p>
      </div>
    </div>
  )
}
