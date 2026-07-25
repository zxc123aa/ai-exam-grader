import { useQuery } from "@tanstack/react-query"
import { useRouterState } from "@tanstack/react-router"
import { useCallback, useEffect, useState } from "react"

import { type ExamPublic, ExamsService } from "@/client"
import useAuth, { isLoggedIn } from "@/hooks/useAuth"

const STORAGE_KEY = "current_exam_id"
const EXAM_PATH_RE = /^\/exams\/([0-9a-f-]{36})/

/**
 * 当前考试上下文：侧栏「批卷工作台 / 改卷报告 / 班级分析 / 重新组卷」
 * 都作用于它。选择持久化到 localStorage，默认取最近一场考试；
 * 直接打开某考试页面时自动跟随路由同步。
 * 学生角色无考试列表权限，不发起查询。
 */
export function useCurrentExam() {
  const { user } = useAuth()
  const isStudent = user?.role === "student"
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  })
  // user 未加载完成时 isStudent 还是 false，需等用户就绪再决定是否发起查询
  const examsQuery = useQuery({
    queryKey: ["exams"],
    queryFn: () => ExamsService.readExams({ skip: 0, limit: 100 }),
    enabled: isLoggedIn() && !!user && !isStudent,
  })
  const exams = examsQuery.data?.data ?? []

  const [examId, setExamId] = useState<string | null>(() =>
    localStorage.getItem(STORAGE_KEY),
  )

  // 直接打开某考试页面（考试管理 → 进入）时，选择器跟随路由
  const routeExamId = EXAM_PATH_RE.exec(pathname)?.[1] ?? null
  useEffect(() => {
    if (routeExamId && routeExamId !== examId) {
      setExamId(routeExamId)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeExamId, examId])

  // 存储的考试被删除或从未选择时，回退到最近一场
  useEffect(() => {
    if (!exams.length) return
    if (!examId || !exams.some((exam) => exam.id === examId)) {
      setExamId(exams[0].id)
    }
  }, [exams, examId])

  useEffect(() => {
    if (examId) localStorage.setItem(STORAGE_KEY, examId)
  }, [examId])

  const setCurrentExam = useCallback((id: string) => setExamId(id), [])

  const currentExam: ExamPublic | undefined = exams.find(
    (exam) => exam.id === examId,
  )

  return {
    exams,
    currentExam,
    currentExamId: currentExam?.id ?? null,
    setCurrentExam,
    isLoading: examsQuery.isLoading,
  }
}
