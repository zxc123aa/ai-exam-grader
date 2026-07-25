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
  | "/exams/$examId/marking"
  | "/exams/$examId/questions"
  | "/exams/$examId/answers"
  | "/exams/$examId/grading"
  | "/exams/$examId/scores"

export type ExamStep = {
  key: ExamStepKey
  label: string
  to: ExamStepRoute
  done: boolean
}

type RecognitionRun = {
  id: string
  status: string
  confirmed_at: string | null
}

type GradingRun = {
  id: string
  status: string
  config_snapshot?: Record<string, unknown>
}

type AnswerRevision = {
  id: string
  status: "draft" | "published"
}

/**
 * 聚合考试各环节的现有查询，推导工作区六个步骤（导入模板卷 → 框选题目 →
 * 确认题目 → 标准答案 → 批改批次 → 成绩）的完成状态与当前应做步骤。
 * 只复用各页面已有的接口与 queryKey，不新增后端 API。
 */
export function useExamProgress(examId: string) {
  const exam = useQuery({
    queryKey: ["exam", examId],
    queryFn: () => ExamsService.readExam({ examId }),
  })
  const files = useQuery({
    queryKey: ["exam-files", examId],
    queryFn: () => ExamsService.readExamFiles({ examId }),
  })
  const regions = useQuery({
    queryKey: ["exam-regions", examId],
    queryFn: () => ExamsService.readExamRegions({ examId }),
  })
  const recognitionRuns = useQuery({
    queryKey: ["question-recognition-runs", examId],
    queryFn: () =>
      workflowApi<{ data: RecognitionRun[] }>(
        `/exams/${examId}/question-recognition-runs`,
      ),
  })
  const questions = useQuery({
    queryKey: ["confirmed-questions", examId],
    queryFn: () =>
      workflowApi<{ data: unknown[]; count: number }>(
        `/exams/${examId}/questions`,
      ),
  })
  const revisions = useQuery({
    queryKey: ["answer-revisions", examId],
    queryFn: () =>
      workflowApi<{ data: AnswerRevision[]; count: number }>(
        `/exams/${examId}/standard-answers/revisions`,
      ),
  })
  const gradingRuns = useQuery({
    queryKey: ["grading-runs", examId],
    queryFn: () =>
      workflowApi<{ data: GradingRun[] }>(`/grading/runs?exam_id=${examId}`),
  })

  const hasPaper = (files.data?.data ?? []).some(
    (document) => document.document_type === "blank_exam",
  )
  const hasRegions =
    (regions.data?.data ?? []).length > 0 ||
    (recognitionRuns.data?.data ?? []).length > 0
  const questionsConfirmed =
    (questions.data?.count ?? 0) > 0 ||
    (recognitionRuns.data?.data ?? []).some((run) => Boolean(run.confirmed_at))
  const answersPublished = (revisions.data?.data ?? []).some(
    (revision) => revision.status === "published",
  )
  const gradingFinished = (gradingRuns.data?.data ?? []).some(
    (run) =>
      run.config_snapshot?.pipeline !== "recognition_preview" &&
      run.status.startsWith("completed"),
  )

  const steps: ExamStep[] = [
    {
      key: "import",
      label: "导入模板卷",
      to: "/exams/$examId/marking",
      done: hasPaper,
    },
    {
      key: "marking",
      label: "框选题目",
      to: "/exams/$examId/marking",
      done: hasRegions,
    },
    {
      key: "questions",
      label: "确认题目",
      to: "/exams/$examId/questions",
      done: questionsConfirmed,
    },
    {
      key: "answers",
      label: "标准答案",
      to: "/exams/$examId/answers",
      done: answersPublished,
    },
    {
      key: "grading",
      label: "批改批次",
      to: "/exams/$examId/grading",
      done: gradingFinished,
    },
    {
      key: "scores",
      label: "成绩",
      to: "/exams/$examId/scores",
      // 存在已完成的批改批次即视为成绩可看
      done: gradingFinished,
    },
  ]

  const currentStep =
    steps.find((step) => !step.done) ?? steps[steps.length - 1]
  const isLoading =
    exam.isPending ||
    files.isPending ||
    regions.isPending ||
    recognitionRuns.isPending ||
    questions.isPending ||
    revisions.isPending ||
    gradingRuns.isPending

  return {
    steps,
    currentStep,
    allDone: steps.every((step) => step.done),
    isLoading,
    exam: exam.data,
  }
}
