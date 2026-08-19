import { createFileRoute, redirect } from "@tanstack/react-router"

// 裸 /my 没有页面：学生入口统一落在「我的成绩」
export const Route = createFileRoute("/_layout/my")({
  beforeLoad: () => {
    throw redirect({ to: "/my/exams", replace: true })
  },
})
