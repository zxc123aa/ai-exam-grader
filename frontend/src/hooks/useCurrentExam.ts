import { useQuery } from "@tanstack/react-query"
import { useRouterState } from "@tanstack/react-router"
import { useCallback, useEffect, useState } from "react"

import { type ExamPublic, ExamsService } from "@/client"
import { resolveRole } from "@/components/Admin/roleMeta"
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
  const canUseExams =
    user != null &&
    ["school_owner", "school_admin", "teacher"].includes(resolveRole(user))
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  })
  // user 未加载完成时 isStudent 还是 false，需等用户就绪再决定是否发起查询
  const examsQuery = useQuery({
    queryKey: ["exams"],
    queryFn: () => ExamsService.readExams({ skip: 0, limit: 100 }),
    enabled: isLoggedIn() && canUseExams,
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
    // 路由直接打开的考试优先：列表只拉前 100 场，老考试可能不在其中；
    // 此时若强行回退到 exams[0]，会与上面的路由同步 effect 互相覆盖，
    // 两个 effect 每轮渲染交替 setExamId，形成无限渲染循环
    if (routeExamId && examId === routeExamId) return
    if (!examId || !exams.some((exam) => exam.id === examId)) {
      setExamId(exams[0].id)
    }
  }, [exams, examId, routeExamId])

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
    // 列表只含前 100 场；路由打开的老考试不在其中时回退到路由 id，
    // 保证侧栏考试相关链接不丢失当前考试上下文
    currentExamId: currentExam?.id ?? routeExamId,
    setCurrentExam,
    isLoading: examsQuery.isLoading,
  }
}
