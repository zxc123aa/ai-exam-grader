import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ClipboardList, UserRound } from "lucide-react"
import type { StudentExamListItemPublic } from "@/client"
import { ApiError, StudentsService } from "@/client"
import { EmptyState } from "@/components/Common/EmptyState"
import { PageHead } from "@/components/Common/PageHead"
import { Tag } from "@/components/Common/Tag"
import { Skeleton } from "@/components/ui/skeleton"

export const Route = createFileRoute("/_layout/my/exams")({
  component: MyExamsPage,
  head: () => ({ meta: [{ title: "我的成绩 - 点凡阅卷" }] }),
})

function formatScore(value: number | null | undefined): string {
  if (value == null) return "--"
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function formatExamDate(value: string | null | undefined): string | null {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
  })
}

function ExamCard({ exam }: { exam: StudentExamListItemPublic }) {
  const meta = [
    exam.subject,
    exam.grade_level,
    formatExamDate(exam.exam_date),
  ].filter(Boolean)
  return (
    <Link
      to="/my/exams/$examId"
      params={{ examId: exam.exam_id }}
      className="flex flex-col gap-3 rounded-2xl bg-card p-5 shadow-card transition-shadow hover:shadow-card-lg"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-semibold leading-snug">{exam.title}</h3>
        {exam.class_name && <Tag variant="neutral">{exam.class_name}</Tag>}
      </div>
      {meta.length > 0 && (
        <p className="text-muted-foreground text-xs">{meta.join(" · ")}</p>
      )}
      <div className="mt-auto flex items-end justify-between gap-2">
        <div className="flex items-baseline gap-1.5">
          <span className="font-bold text-3xl tracking-tight">
            {formatScore(exam.total_score)}
          </span>
          <span className="text-muted-foreground text-sm">
            / {formatScore(exam.total_max_score)} 分
          </span>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <span className="text-muted-foreground text-xs">
            {exam.class_rank != null
              ? `第 ${exam.class_rank} / ${exam.class_size ?? "--"} 名`
              : "暂无排名"}
          </span>
          {(exam.pending_review_count ?? 0) > 0 && (
            <Tag variant="amber">批改复核中</Tag>
          )}
        </div>
      </div>
    </Link>
  )
}

function MyExamsPage() {
  const query = useQuery({
    queryKey: ["my-exams"],
    queryFn: () => StudentsService.readMyExams(),
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 3,
  })

  const isUnbound =
    query.error instanceof ApiError && query.error.status === 404

  return (
    <div className="flex flex-col gap-6">
      <PageHead title="我的成绩" subtitle="你参加过的考试与得分" />
      {query.isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {["s1", "s2", "s3"].map((key) => (
            <Skeleton key={key} className="h-40 rounded-2xl" />
          ))}
        </div>
      ) : isUnbound ? (
        <EmptyState
          icon={UserRound}
          title="账号未绑定学生档案"
          description="请联系老师将你的账号绑定到班级学生档案后查看成绩"
        />
      ) : query.isError ? (
        <p className="text-destructive text-sm">
          成绩数据加载失败：{String(query.error)}
        </p>
      ) : (query.data?.data.length ?? 0) === 0 ? (
        <EmptyState
          icon={ClipboardList}
          title="还没有已批改的考试"
          description="老师批改出分后，你的考试成绩会显示在这里"
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {query.data?.data.map((exam) => (
            <ExamCard key={exam.exam_id} exam={exam} />
          ))}
        </div>
      )}
    </div>
  )
}
