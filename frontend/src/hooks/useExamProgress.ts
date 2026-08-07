import { useQuery } from "@tanstack/react-query"

import { ExamsService } from "@/client"
import { workflowApi } from "@/lib/workflow-api"

export type ExamStepKey =
  | "import"
  | "marking"
  | "questions"
  | "answers"
  | "grading"
  | "scores"

export type ExamStepRoute =
  | "/exams/$examId"
  | "/exams/$examId/marking"
  | "/exams/$examId/questions"
  | "/exams/$examId/answers"
  | "/exams/$examId/grading"
  | "/exams/$examId/scores"
  | "/exams/$examId/workbench"

export type ExamStep = {
  key: ExamStepKey
  label: string
  to: ExamStepRoute
  done: boolean
}

type WorkflowSummary = {
  next_action: string
  next_label: string
  next_path: string
  message: string
  steps: Array<{
    code: ExamStepKey
    label: string
    status: "pending" | "active" | "completed" | "blocked"
    count: number
  }>
}

const STEP_ROUTES: Record<ExamStepKey, ExamStepRoute> = {
  import: "/exams/$examId",
  marking: "/exams/$examId/marking",
  questions: "/exams/$examId/questions",
  answers: "/exams/$examId/answers",
  grading: "/exams/$examId/grading",
  scores: "/exams/$examId/scores",
}

function routeFromPath(path: string): ExamStepRoute {
  if (path.endsWith("/workbench")) return "/exams/$examId/workbench"
  if (path.endsWith("/questions")) return "/exams/$examId/questions"
  if (path.endsWith("/answers")) return "/exams/$examId/answers"
  if (path.endsWith("/grading")) return "/exams/$examId/grading"
  if (path.endsWith("/scores")) return "/exams/$examId/scores"
  if (/\/exams\/[^/]+\/?$/.test(path)) return "/exams/$examId"
  return "/exams/$examId/marking"
}

const ACTION_STEP: Record<string, ExamStepKey> = {
  import_paper: "import",
  mark_questions: "marking",
  confirm_questions: "questions",
  prepare_answers: "answers",
  import_submissions: "grading",
  wait_grading: "grading",
  start_grading: "grading",
  review_exceptions: "grading",
  publish_scores: "scores",
  view_results: "scores",
}

/**
 * 后端统一汇总考试进度，前端只展示老师下一步该做什么。
 * 避免列表每行并发请求多个业务接口造成等待和状态不一致。
 */
export function useExamProgress(examId: string) {
  const exam = useQuery({
    queryKey: ["exam", examId],
    queryFn: () => ExamsService.readExam({ examId }),
  })
  const summary = useQuery({
    queryKey: ["exam-workflow-summary", examId],
    queryFn: () =>
      workflowApi<WorkflowSummary>(`/exams/${examId}/workflow-summary`),
  })

  const steps: ExamStep[] = (summary.data?.steps ?? []).map((step) => ({
    key: step.code,
    label: step.label,
    to: STEP_ROUTES[step.code],
    done: step.status === "completed",
  }))
  const fallback = steps[0] ?? {
    key: "import" as const,
    label: "导入模板卷",
    to: "/exams/$examId" as const,
    done: false,
  }
  const currentStep = summary.data
    ? {
        key: ACTION_STEP[summary.data.next_action] ?? fallback.key,
        label: summary.data.next_label,
        to: routeFromPath(summary.data.next_path),
        done: summary.data.next_action === "view_results",
      }
    : fallback

  return {
    steps,
    currentStep,
    allDone: summary.data?.next_action === "view_results",
    isLoading: exam.isPending || summary.isPending,
    exam: exam.data,
    message: summary.data?.message,
  }
}
