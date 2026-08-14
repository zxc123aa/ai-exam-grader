import {
  createFileRoute,
  Navigate,
  Outlet,
  Link as RouterLink,
  redirect,
  useNavigate,
  useRouterState,
} from "@tanstack/react-router"
import { Bell, LogOut, Search, Settings } from "lucide-react"

import { ROLE_LABELS, resolveRole } from "@/components/Admin/roleMeta"
import { AvatarGradient } from "@/components/Common/AvatarGradient"
import { StudentTabBar } from "@/components/Common/StudentTabBar"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import useAuth, { isLoggedIn } from "@/hooks/useAuth"
import { useCurrentExam } from "@/hooks/useCurrentExam"
import useCustomToast from "@/hooks/useCustomToast"
import { cn } from "@/lib/utils"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({
        to: "/login",
      })
    }
  },
})

/** 顶栏页面标题：按路径段推导，与侧栏导航对齐。 */
const TITLE_BY_SEGMENT: Record<string, string> = {
  exams: "导入试卷",
  my: "我的成绩",
  marking: "框选题目",
  questions: "确认题目",
  answers: "标准答案",
  grading: "批卷工作台",
  workbench: "批卷工作台",
  submissions: "批卷工作台",
  review: "人工复核",
  report: "改卷报告",
  scores: "班级分析",
  compose: "重新组卷",
  classes: "班级学生",
  admin: "用户管理",
  platform: "学校管理",
  "org-settings": "学校设置",
  settings: "个人设置",
  "getting-started": "首次开通",
}

function pageTitle(pathname: string) {
  if (pathname === "/") return "工作台"
  if (pathname === "/exams") return "考试管理"
  // 平台子页先于逐段匹配：/platform/settings 是卖方模型控制面。
  if (pathname === "/platform/settings") return "中转与方案"
  if (pathname === "/platform/routing") return "功能调度"
  if (pathname === "/platform/usage") return "调用记录"
  // 学生端路径优先：/my/exams 的 exams 段不能被误判为「导入试卷」
  if (pathname.startsWith("/my")) {
    return pathname === "/my/exams" ? "我的成绩" : "成绩报告"
  }
  const segments = pathname.split("/").filter(Boolean)
  for (let i = segments.length - 1; i >= 0; i--) {
    const title = TITLE_BY_SEGMENT[segments[i]]
    if (title) return title
  }
  return "工作台"
}

function ExamSelector() {
  const { exams, currentExamId, setCurrentExam } = useCurrentExam()
  const navigate = useNavigate()
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  })

  if (!exams.length) return null

  return (
    <Select
      value={currentExamId ?? undefined}
      onValueChange={(id) => {
        setCurrentExam(id)
        // 当前在某考试工作区内时，切换到新考试的同一视图
        if (currentExamId && pathname.includes(`/exams/${currentExamId}`)) {
          navigate({
            to: pathname.replace(`/exams/${currentExamId}`, `/exams/${id}`),
          })
        }
      }}
    >
      <SelectTrigger
        className="h-9 min-w-0 w-40 rounded-full border-border bg-card text-xs sm:w-56"
        data-testid="exam-selector"
      >
        <SelectValue placeholder="选择考试" />
      </SelectTrigger>
      <SelectContent>
        {exams.map((exam) => (
          <SelectItem key={exam.id} value={exam.id}>
            {exam.title}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function TopbarUser() {
  const { user, logout } = useAuth()
  if (!user) return null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <AvatarGradient name={user.full_name || "用户"} size={34} />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-56 rounded-xl">
        <DropdownMenuLabel className="font-normal">
          <div className="flex items-center gap-2.5">
            <AvatarGradient name={user.full_name || "用户"} size={32} />
            <div className="flex min-w-0 flex-col">
              <p className="truncate text-sm font-medium">
                {user.full_name}
                <span className="ml-1.5 font-normal text-muted-foreground text-xs">
                  {ROLE_LABELS[resolveRole(user)]}
                </span>
              </p>
              <p className="truncate text-xs text-muted-foreground">
                {user.email}
              </p>
            </div>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <RouterLink to="/settings">
          <DropdownMenuItem>
            <Settings />
            个人设置
          </DropdownMenuItem>
        </RouterLink>
        <DropdownMenuItem onClick={() => logout()}>
          <LogOut />
          退出登录
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function Layout() {
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  })
  const { showInfoToast } = useCustomToast()
  const { user } = useAuth()
  const role = user ? resolveRole(user) : "teacher"
  const isStudent = user ? role === "student" : false
  const isPlatform = role.startsWith("platform_")

  // 学生只能访问 /my/* 和个人设置，其余路径送回「我的成绩」
  if (isStudent && !pathname.startsWith("/my") && pathname !== "/settings") {
    return <Navigate to="/my/exams" replace />
  }
  const platformPathAllowed =
    pathname.startsWith("/platform") ||
    pathname === "/settings" ||
    (role === "platform_superuser" && pathname === "/admin")
  if (isPlatform && !platformPathAllowed) {
    return <Navigate to="/platform" replace />
  }

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="sticky top-0 z-10 flex h-16 shrink-0 items-center gap-2 border-b bg-background/85 px-3 backdrop-blur sm:gap-4 sm:px-6">
          <SidebarTrigger className="-ml-1 text-muted-foreground" />
          <h1 className="hidden whitespace-nowrap text-lg font-bold sm:block">
            {pathname === "/admin" && isPlatform
              ? "平台账号"
              : pageTitle(pathname)}
          </h1>
          <div className="ml-auto flex min-w-0 items-center gap-2 sm:gap-3">
            {!isStudent && !isPlatform && (
              <>
                <ExamSelector />
                <div className="hidden items-center gap-2 rounded-full border bg-card px-4 py-2 text-muted-foreground transition-all focus-within:border-primary focus-within:shadow-[0_0_0_3px_rgba(46,91,255,0.12)] md:flex md:w-64">
                  <Search className="size-3.5" />
                  <input
                    className="w-full bg-transparent text-[13px] outline-none placeholder:text-muted-foreground"
                    placeholder="搜索学生 / 考试 / 知识点…"
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && e.currentTarget.value.trim()) {
                        showInfoToast("全局搜索将在后续版本提供")
                        e.currentTarget.value = ""
                      }
                    }}
                  />
                </div>
              </>
            )}
            <button
              type="button"
              className="relative flex size-9 items-center justify-center rounded-[10px] border bg-card text-muted-foreground transition-all hover:border-primary hover:text-primary"
              onClick={() => showInfoToast("暂无新通知")}
              aria-label="通知"
            >
              <Bell className="size-4" />
              <i className="absolute top-1.5 right-1.5 size-2 rounded-full border-2 border-card bg-red-500" />
            </button>
            <TopbarUser />
          </div>
        </header>
        <main
          className={cn(
            "flex-1 p-5 md:p-6",
            // 给移动底部导航留出空间，否则最后一条内容会被遮住
            isStudent && "pb-20 md:pb-6",
          )}
        >
          <div className="mx-auto max-w-7xl">
            <Outlet />
          </div>
        </main>
        {isStudent && <StudentTabBar pathname={pathname} />}
      </SidebarInset>
    </SidebarProvider>
  )
}

export default Layout
