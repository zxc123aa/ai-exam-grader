import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowDownWideNarrow, ArrowUpNarrowWide, Download } from "lucide-react"
import { useMemo, useState } from "react"
import type { ExamScoreSummaryRow } from "@/client"
import { ExamsService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

export const Route = createFileRoute("/_layout/exams_/$examId/scores")({
  component: ScoresOverview,
  head: () => ({ meta: [{ title: "成绩总览 - 智阅卷" }] }),
})

const UNASSIGNED_CLASS = "未分班"

type MergedQuestion = {
  label: string
  score: number | null
  maxScore: number | null
  source: "final" | "ai_suggested" | null
}

type MergedStudent = {
  key: string
  className: string
  studentName: string
  studentIdentifier: string | null
  totalScore: number | null
  totalMaxScore: number | null
  questions: Map<string, MergedQuestion>
  pendingReviewCount: number
  reviewSubmissionId: string | null
  registrationFailed: boolean
}

/**
 * 合并口径：一个学生可能有多张答卷照片（多条 submission），按
 * 「班级 + 学生姓名」合并为一行——
 * - 总分 / 满分 = 各 submission 之和（全部为空则视为无成绩）；
 * - 各题按题号 label 合并，同 label 出现多次时取 final（已复核）来源优先，
 *   其余保留先出现的非空分数；
 * - pending_review_count 求和；
 * - 「复核」链接指向最后一条 submission（接口按时间倒序返回时即最新一条之后的
 *   最旧一条，这里取行内出现顺序的最后一条作为兜底）。
 */
function mergeStudents(rows: ExamScoreSummaryRow[]): MergedStudent[] {
  const map = new Map<string, MergedStudent>()
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
        pendingReviewCount: 0,
        reviewSubmissionId: null,
        registrationFailed: false,
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
      const incoming: MergedQuestion = {
        label: question.label,
        score: question.score ?? null,
        maxScore: question.max_score ?? null,
        source,
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
    student.pendingReviewCount += row.pending_review_count ?? 0
    student.reviewSubmissionId = row.submission_id
    if (row.registration_status === "failed") {
      student.registrationFailed = true
    }
  }
  return [...map.values()]
}

function sortLabels(labels: string[]): string[] {
  return [...labels].sort((a, b) =>
    a.localeCompare(b, "zh-Hans-CN", { numeric: true }),
  )
}

function formatScore(value: number | null): string {
  if (value == null) return "--"
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function csvCell(value: string | number | null | undefined): string {
  const text = value == null ? "" : String(value)
  return `"${text.replace(/"/g, '""')}"`
}

function ScoresOverview() {
  const { examId } = Route.useParams()
  const [classFilter, setClassFilter] = useState("all")
  const [sortOrder, setSortOrder] = useState<"default" | "desc" | "asc">(
    "default",
  )

  const exam = useQuery({
    queryKey: ["exam", examId],
    queryFn: () => ExamsService.readExam({ examId }),
  })
  const summary = useQuery({
    queryKey: ["exam-score-summary", examId],
    queryFn: () => ExamsService.readExamScoresSummary({ examId }),
  })

  const rows = useMemo(() => summary.data?.data ?? [], [summary.data])
  const students = useMemo(() => mergeStudents(rows), [rows])

  const classNames = useMemo(
    () => [...new Set(students.map((student) => student.className))].sort(),
    [students],
  )

  const filtered = useMemo(() => {
    const list =
      classFilter === "all"
        ? students
        : students.filter((student) => student.className === classFilter)
    if (sortOrder === "default") return list
    return [...list].sort((a, b) => {
      const left = a.totalScore ?? Number.NEGATIVE_INFINITY
      const right = b.totalScore ?? Number.NEGATIVE_INFINITY
      return sortOrder === "desc" ? right - left : left - right
    })
  }, [students, classFilter, sortOrder])

  const questionLabels = useMemo(() => {
    const labels = new Set<string>()
    for (const student of filtered) {
      for (const label of student.questions.keys()) labels.add(label)
    }
    return sortLabels([...labels])
  }, [filtered])

  const groups = useMemo(() => {
    const map = new Map<string, MergedStudent[]>()
    for (const student of filtered) {
      const list = map.get(student.className)
      if (list) list.push(student)
      else map.set(student.className, [student])
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [filtered])

  const stats = useMemo(() => {
    const scored = filtered.filter((student) => student.totalScore != null)
    const scores = scored.map((student) => student.totalScore as number)
    const pending = filtered.filter(
      (student) => student.pendingReviewCount > 0,
    ).length
    return {
      scoredCount: scored.length,
      average:
        scores.length > 0
          ? scores.reduce((sum, value) => sum + value, 0) / scores.length
          : null,
      max: scores.length > 0 ? Math.max(...scores) : null,
      min: scores.length > 0 ? Math.min(...scores) : null,
      pending,
    }
  }, [filtered])

  const hasSubmissions = rows.length > 0
  const hasScores = students.some((student) => student.totalScore != null)

  function exportCsv() {
    const header = ["班级", "学生", "学号", "总分", ...questionLabels]
    const lines = [header.map(csvCell).join(",")]
    for (const [className, members] of groups) {
      for (const student of members) {
        const cells: Array<string | number | null> = [
          className,
          student.studentName,
          student.studentIdentifier,
          student.totalScore,
        ]
        for (const label of questionLabels) {
          cells.push(student.questions.get(label)?.score ?? null)
        }
        lines.push(cells.map(csvCell).join(","))
      }
    }
    // 加 BOM 保证 Excel 直接打开不乱码
    const blob = new Blob([`﻿${lines.join("\r\n")}`], {
      type: "text/csv;charset=utf-8",
    })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement("a")
    const date = new Date().toISOString().slice(0, 10)
    anchor.href = url
    anchor.download = `${exam.data?.title ?? "考试"}-成绩-${date}.csv`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  if (summary.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (summary.isError) {
    return (
      <p className="text-sm text-destructive">
        成绩数据加载失败：{String(summary.error)}
      </p>
    )
  }

  if (!hasSubmissions) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-muted-foreground">
          还没有学生答卷。请先在「导入」步骤的导入中心上传学生答卷照片。
        </CardContent>
      </Card>
    )
  }

  if (!hasScores) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-muted-foreground">
          已导入 {rows.length} 份答卷，但还没有批改数据。请先在
          <Link
            to="/exams/$examId/grading"
            params={{ examId }}
            className="mx-1 underline"
          >
            批量批改
          </Link>
          步骤完成批改。
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-6 rounded-md border px-4 py-3 text-sm">
          <div>
            <span className="text-muted-foreground">参考人数</span>
            <p className="text-lg font-semibold">{stats.scoredCount}</p>
          </div>
          <div>
            <span className="text-muted-foreground">平均分</span>
            <p className="text-lg font-semibold">
              {stats.average == null ? "--" : stats.average.toFixed(1)}
            </p>
          </div>
          <div>
            <span className="text-muted-foreground">最高分</span>
            <p className="text-lg font-semibold">{formatScore(stats.max)}</p>
          </div>
          <div>
            <span className="text-muted-foreground">最低分</span>
            <p className="text-lg font-semibold">{formatScore(stats.min)}</p>
          </div>
          <div>
            <span className="text-muted-foreground">待复核</span>
            <p
              className={cn(
                "text-lg font-semibold",
                stats.pending > 0 && "text-amber-600",
              )}
            >
              {stats.pending}
            </p>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Select value={classFilter} onValueChange={setClassFilter}>
            <SelectTrigger className="w-36">
              <SelectValue placeholder="全部班级" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部班级</SelectItem>
              {classNames.map((className) => (
                <SelectItem key={className} value={className}>
                  {className}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={sortOrder}
            onValueChange={(value) =>
              setSortOrder(value as "default" | "desc" | "asc")
            }
          >
            <SelectTrigger className="w-36">
              <SelectValue placeholder="排序" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="default">默认排序</SelectItem>
              <SelectItem value="desc">
                <span className="flex items-center gap-1">
                  <ArrowDownWideNarrow className="size-3.5" />
                  总分从高到低
                </span>
              </SelectItem>
              <SelectItem value="asc">
                <span className="flex items-center gap-1">
                  <ArrowUpNarrowWide className="size-3.5" />
                  总分从低到高
                </span>
              </SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={exportCsv}>
            <Download className="mr-1 size-4" />
            导出 CSV
          </Button>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        图例：<span className="italic text-muted-foreground">斜体</span>= AI
        建议分，未复核；常规字体 = 已复核的最终分。
      </p>
      {groups.map(([className, members]) => {
        const scores = members
          .map((student) => student.totalScore)
          .filter((value): value is number => value != null)
        const classAverage =
          scores.length > 0
            ? scores.reduce((sum, value) => sum + value, 0) / scores.length
            : null
        return (
          <Card key={className}>
            <CardHeader>
              <CardTitle className="flex flex-wrap items-center gap-3 text-base">
                {className}
                <span className="text-sm font-normal text-muted-foreground">
                  {members.length} 人 · 班级平均分{" "}
                  {classAverage == null ? "--" : classAverage.toFixed(1)}
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="py-2 pr-3">学生</th>
                    <th className="py-2 pr-3">学号</th>
                    <th className="py-2 pr-3">总分</th>
                    {questionLabels.map((label) => (
                      <th key={label} className="py-2 pr-3">
                        {label}
                      </th>
                    ))}
                    <th className="py-2 pr-3">待复核</th>
                    <th className="py-2 pr-3">状态</th>
                    <th className="py-2 text-right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {members.map((student) => (
                    <tr className="border-b last:border-0" key={student.key}>
                      <td className="py-2 pr-3 font-medium">
                        {student.studentName}
                      </td>
                      <td className="py-2 pr-3">
                        {student.studentIdentifier ?? "--"}
                      </td>
                      <td className="py-2 pr-3">
                        <span className="font-medium">
                          {formatScore(student.totalScore)}
                        </span>
                        {student.totalMaxScore != null && (
                          <span className="text-muted-foreground">
                            {" "}
                            / {formatScore(student.totalMaxScore)}
                          </span>
                        )}
                      </td>
                      {questionLabels.map((label) => {
                        const question = student.questions.get(label)
                        return (
                          <td key={label} className="py-2 pr-3">
                            {question?.score == null ? (
                              "--"
                            ) : (
                              <span
                                className={cn(
                                  question.source === "ai_suggested" &&
                                    "italic text-muted-foreground",
                                )}
                              >
                                {formatScore(question.score)}
                              </span>
                            )}
                          </td>
                        )
                      })}
                      <td className="py-2 pr-3">
                        {student.pendingReviewCount > 0 ? (
                          <Badge variant="secondary">
                            {student.pendingReviewCount} 题
                          </Badge>
                        ) : (
                          "--"
                        )}
                      </td>
                      <td className="py-2 pr-3">
                        {student.registrationFailed ? (
                          <Badge variant="destructive">登记失败</Badge>
                        ) : student.pendingReviewCount > 0 ? (
                          <Badge variant="secondary">待复核</Badge>
                        ) : student.totalScore != null ? (
                          <Badge>已出分</Badge>
                        ) : (
                          <Badge variant="outline">未批改</Badge>
                        )}
                      </td>
                      <td className="py-2 text-right">
                        {student.reviewSubmissionId && (
                          <Button variant="outline" size="sm" asChild>
                            <Link
                              to="/exams/$examId/submissions/$submissionId/review"
                              params={{
                                examId,
                                submissionId: student.reviewSubmissionId,
                              }}
                            >
                              复核
                            </Link>
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}
