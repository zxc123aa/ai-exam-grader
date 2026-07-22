import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowRight } from "lucide-react"
import { Suspense } from "react"

import { type ExamPublic, ExamsService } from "@/client"
import AddExam from "@/components/Exams/AddExam"
import { Button } from "@/components/ui/button"
import useAuth from "@/hooks/useAuth"
import { useExamProgress } from "@/hooks/useExamProgress"

const WORKFLOW_LABELS = ["导入", "区域校正", "识别内容", "标准答案", "批量批改"]

function getExamsQueryOptions() {
  return {
    queryFn: () => ExamsService.readExams({ skip: 0, limit: 100 }),
    queryKey: ["exams"],
  }
}

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({
    meta: [
      {
        title: "工作台 - 智阅卷",
      },
    ],
  }),
})

/** 试卷头上下双横线——外粗内细，复刻印刷卷面的版式。 */
function PaperRule() {
  return (
    <div aria-hidden className="flex flex-col gap-[3px]">
      <div className="border-t-2 border-foreground/60" />
      <div className="border-t border-foreground/40" />
    </div>
  )
}

/** 红笔印章：微旋转的圆形描边，标注当前进度。全站仅此一枚。 */
function RedSeal({ label }: { label: string }) {
  return (
    <div
      aria-hidden
      className="pointer-events-none flex h-20 w-20 rotate-[-8deg] items-center justify-center rounded-full border-2 border-destructive/70 bg-destructive/5 font-display text-sm font-semibold text-destructive/90"
    >
      {label}
    </div>
  )
}

/** Hero：最近一场考试，以试卷头的版式呈现，右侧盖进度印章。 */
function ContinueHero({ exam }: { exam: ExamPublic }) {
  const { currentStep, allDone, isLoading } = useExamProgress(exam.id)

  return (
    <section className="animate-in fade-in-0 slide-in-from-bottom-2 rounded-xl border bg-card px-6 py-6 shadow-sm duration-500 sm:px-10">
      <PaperRule />
      <div className="relative flex flex-col items-center gap-3 py-8 text-center">
        <div className="absolute top-4 right-0 hidden sm:block">
          <RedSeal label={allDone ? "已批完" : currentStep.label} />
        </div>
        <p className="text-muted-foreground text-xs tracking-[0.3em]">
          上次批改到这里
        </p>
        <h2 className="font-display max-w-xl text-2xl font-bold text-balance sm:text-3xl">
          {exam.title}
        </h2>
        <p className="text-muted-foreground text-sm">
          {[exam.subject, exam.grade_level].filter(Boolean).join(" · ") ||
            "未设置科目"}
        </p>
      </div>
      <PaperRule />
      <div className="flex flex-col items-center justify-between gap-4 pt-6 sm:flex-row">
        <ol className="text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
          {WORKFLOW_LABELS.map((label, index) => (
            <li key={label} className="flex items-center gap-2">
              {index > 0 && <span aria-hidden>→</span>}
              <span
                className={
                  !isLoading && label === currentStep.label && !allDone
                    ? "font-medium text-foreground"
                    : undefined
                }
              >
                {label}
              </span>
            </li>
          ))}
        </ol>
        <Button asChild>
          <Link to={currentStep.to} params={{ examId: exam.id }}>
            {allDone ? "查看批改结果" : `继续：${currentStep.label}`}
            <ArrowRight />
          </Link>
        </Button>
      </div>
    </section>
  )
}

function RecentExamRow({ exam }: { exam: ExamPublic }) {
  const { currentStep, allDone, isLoading } = useExamProgress(exam.id)

  return (
    <li className="flex items-center justify-between gap-4 py-3">
      <div className="min-w-0">
        <Link
          to={currentStep.to}
          params={{ examId: exam.id }}
          className="font-display truncate font-medium hover:text-primary"
        >
          {exam.title}
        </Link>
        <p className="text-muted-foreground mt-0.5 text-xs">
          {exam.subject || "未设置科目"}
          <span aria-hidden className="mx-2">
            ·
          </span>
          {isLoading
            ? "进度加载中…"
            : allDone
              ? "已完成"
              : `进度：${currentStep.label}`}
        </p>
      </div>
      <Button variant="outline" size="sm" asChild>
        <Link to={currentStep.to} params={{ examId: exam.id }}>
          继续
          <ArrowRight />
        </Link>
      </Button>
    </li>
  )
}

function DashboardContent() {
  const { data: exams } = useSuspenseQuery(getExamsQueryOptions())
  const [latest, ...rest] = exams.data

  if (!latest) {
    return (
      <section className="animate-in fade-in-0 slide-in-from-bottom-2 rounded-xl border bg-card px-6 py-6 shadow-sm duration-500 sm:px-10">
        <PaperRule />
        <div className="flex flex-col items-center gap-3 py-10 text-center">
          <h2 className="font-display text-2xl font-bold sm:text-3xl">
            第一场考试，从一张卷子开始
          </h2>
          <p className="text-muted-foreground max-w-md text-sm">
            创建考试后导入空白试卷的图片或
            PDF，识别题目、准备标准答案，再批量批改学生答卷。
          </p>
          <div className="mt-2">
            <AddExam />
          </div>
        </div>
        <PaperRule />
      </section>
    )
  }

  return (
    <>
      <ContinueHero exam={latest} />
      {rest.length > 0 && (
        <section className="animate-in fade-in-0 slide-in-from-bottom-2 duration-500 delay-150">
          <div className="flex items-baseline justify-between">
            <h3 className="text-sm font-medium">最近考试</h3>
            <Link
              to="/exams"
              className="text-muted-foreground text-xs hover:text-foreground"
            >
              查看全部 →
            </Link>
          </div>
          <ul className="divide-border mt-2 divide-y border-y">
            {rest.slice(0, 5).map((exam) => (
              <RecentExamRow key={exam.id} exam={exam} />
            ))}
          </ul>
        </section>
      )}
    </>
  )
}

function Dashboard() {
  const { user: currentUser } = useAuth()

  return (
    <div className="flex flex-col gap-8">
      <div className="animate-in fade-in-0 duration-300">
        <p className="text-muted-foreground text-sm">
          {currentUser?.full_name || currentUser?.email}
        </p>
        <h1 className="font-display text-3xl font-bold tracking-tight">
          工作台
        </h1>
      </div>
      <Suspense
        fallback={
          <div className="text-muted-foreground rounded-xl border border-dashed px-6 py-16 text-center text-sm">
            正在加载考试…
          </div>
        }
      >
        <DashboardContent />
      </Suspense>
    </div>
  )
}
