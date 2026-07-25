import { Link, useRouterState } from "@tanstack/react-router"
import { ChevronRight, Circle, CircleCheck } from "lucide-react"
import { Fragment } from "react"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { type ExamStepKey, useExamProgress } from "@/hooks/useExamProgress"
import { cn } from "@/lib/utils"

function resolveActiveStep(
  pathname: string,
  importDone: boolean,
  examId: string,
): ExamStepKey {
  if (pathname.includes("/questions")) return "questions"
  if (pathname.includes("/answers")) return "answers"
  if (pathname.includes("/grading")) return "grading"
  if (pathname.includes("/scores")) return "scores"
  // 导入页（/exams/$id 本身）高亮“导入卷面”
  if (pathname === `/exams/${examId}` || pathname === `/exams/${examId}/`) {
    return "import"
  }
  // marking 页同时承担“导入卷面”入口：尚未导入试卷时高亮“导入卷面”
  return importDone ? "marking" : "import"
}

export function ExamWorkspaceNav({ examId }: { examId: string }) {
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  })
  const { steps, isLoading } = useExamProgress(examId)

  if (isLoading) {
    return <Skeleton className="h-12 w-full rounded-2xl" />
  }

  const activeKey = resolveActiveStep(
    pathname,
    steps.find((step) => step.key === "import")?.done ?? false,
    examId,
  )
  const activeIndex = steps.findIndex((step) => step.key === activeKey)
  const activeStep = steps[activeIndex]
  const nextStep = steps[activeIndex + 1]
  const showNext = activeStep?.done && nextStep && nextStep.to !== activeStep.to

  return (
    <nav
      aria-label="考试工作区步骤"
      className="flex flex-wrap items-center gap-1.5 rounded-2xl border bg-card p-2 shadow-card"
    >
      {steps.map((step, index) => {
        const isActive = step.key === activeKey
        const stepClassName = cn(
          "flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          isActive
            ? "bg-primary font-medium text-primary-foreground"
            : step.done
              ? "text-foreground hover:bg-accent"
              : "text-muted-foreground hover:bg-accent hover:text-foreground",
        )
        const stepIcon = step.done ? (
          <CircleCheck
            className={cn("size-4", !isActive && "text-emerald-500")}
          />
        ) : (
          <Circle className="size-4" />
        )
        return (
          <Fragment key={step.key}>
            {index > 0 && (
              <ChevronRight className="size-4 shrink-0 text-muted-foreground/50" />
            )}
            <Link
              to={step.key === "import" ? "/exams/$examId" : step.to}
              params={{ examId }}
              aria-current={isActive ? "step" : undefined}
              className={stepClassName}
            >
              {stepIcon}
              {step.label}
            </Link>
          </Fragment>
        )
      })}
      {showNext && (
        <Button
          asChild
          size="sm"
          className="ml-auto bg-gradient-primary text-white hover:opacity-90"
        >
          <Link to={nextStep.to} params={{ examId }}>
            下一步：{nextStep.label}
          </Link>
        </Button>
      )}
    </nav>
  )
}
