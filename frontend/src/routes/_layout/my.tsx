import { createFileRoute, redirect } from "@tanstack/react-router"

// 裸 /my 没有页面：学生入口统一落在「我的成绩」。
// 注意：/my 是 my.* 子路由的父级，beforeLoad 对子路径也会触发——
// 必须只在精确匹配 /my 时重定向，否则 /my/exams 会被循环重定向卡死。
export const Route = createFileRoute("/_layout/my")({
  beforeLoad: ({ location }) => {
    if (location.pathname === "/my" || location.pathname === "/my/") {
      throw redirect({ to: "/my/exams", replace: true })
    }
  },
})
