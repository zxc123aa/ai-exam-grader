import { Link as RouterLink, useRouterState } from "@tanstack/react-router"
import {
  BarChart3,
  Building2,
  FileText,
  GraduationCap,
  LayoutDashboard,
  NotebookPen,
  PenLine,
  Settings2,
  ShieldCheck,
  Upload,
  Users,
} from "lucide-react"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { useCurrentExam } from "@/hooks/useCurrentExam"
import { cn } from "@/lib/utils"
import { resolveRole } from "../Admin/roleMeta"
import { User } from "./User"

type NavItem = {
  icon: typeof LayoutDashboard
  title: string
  /** 需要选中考试才有意义（指向 /exams/$examId 下的页面） */
  examScoped?: boolean
  /** 计算链接目标；examScoped 项会收到当前考试 id */
  to: (examId: string | null) => string
  /** 激活匹配：当前路径前缀 */
  activePrefixes: (examId: string | null) => string[]
}

/** 侧栏激活项统一样式：纯色品牌紫 + 白字（覆盖组件默认的淡色 accent）。 */
const ACTIVE_ITEM_CLASS =
  "bg-primary shadow-[0_6px_16px_rgba(46,91,255,0.3)] data-[active=true]:bg-primary data-[active=true]:text-white data-[active=true]:hover:text-white dark:shadow-none"

const MAIN_ITEMS: NavItem[] = [
  {
    icon: LayoutDashboard,
    title: "工作台",
    to: () => "/",
    activePrefixes: () => ["/"],
  },
  {
    icon: FileText,
    title: "考试管理",
    to: () => "/exams",
    activePrefixes: () => ["/exams"],
  },
  {
    icon: Upload,
    title: "导入试卷",
    examScoped: true,
    to: (id) => (id ? `/exams/${id}` : "/exams"),
    activePrefixes: (id) =>
      id
        ? [
            `/exams/${id}/marking`,
            `/exams/${id}/questions`,
            `/exams/${id}/answers`,
          ]
        : [],
  },
  {
    icon: PenLine,
    title: "批卷工作台",
    examScoped: true,
    to: (id) => (id ? `/exams/${id}/workbench` : "/exams"),
    activePrefixes: (id) =>
      id
        ? [
            `/exams/${id}/workbench`,
            `/exams/${id}/grading`,
            `/exams/${id}/submissions`,
          ]
        : [],
  },
  {
    icon: FileText,
    title: "改卷报告",
    examScoped: true,
    to: (id) => (id ? `/exams/${id}/report` : "/exams"),
    activePrefixes: (id) => (id ? [`/exams/${id}/report`] : []),
  },
  {
    icon: BarChart3,
    title: "班级分析",
    examScoped: true,
    to: (id) => (id ? `/exams/${id}/scores` : "/exams"),
    activePrefixes: (id) => (id ? [`/exams/${id}/scores`] : []),
  },
  {
    icon: NotebookPen,
    title: "重新组卷",
    to: () => "/compose",
    activePrefixes: () => ["/compose"],
  },
]

function isItemActive(item: NavItem, examId: string | null, path: string) {
  if (item.title === "工作台") return path === "/"
  // 考试管理只在列表页本身高亮（/exams/$id 下的页面归各功能项）
  if (item.title === "考试管理") return path === "/exams"
  // 考试概览页（/exams/$id 本身）归入「导入试卷」
  if (item.title === "导入试卷" && examId && path === `/exams/${examId}`) {
    return true
  }
  return item.activePrefixes(examId).some((prefix) => path.startsWith(prefix))
}

export function AppSidebar() {
  const { user: currentUser } = useAuth()
  const { currentExamId } = useCurrentExam()
  const { isMobile, setOpenMobile } = useSidebar()
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  })

  const handleMenuClick = () => {
    if (isMobile) setOpenMobile(false)
  }

  // 角色：resolveRole 兼容旧枚举值与 is_superuser 标志
  const role = currentUser ? resolveRole(currentUser) : ("teacher" as const)
  const isStudent = role === "student"
  const isPlatform =
    role === "platform_superuser" || role === "platform_support"
  const isPlatformSuperuser = role === "platform_superuser"
  const isSchoolAdmin = role === "school_owner" || role === "school_admin"

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-5 group-data-[collapsible=icon]:px-2 group-data-[collapsible=icon]:items-center">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        {isStudent ? (
          <SidebarGroup>
            <SidebarGroupLabel className="text-sidebar-foreground/50">
              我的学习
            </SidebarGroupLabel>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  tooltip="我的成绩"
                  isActive={pathname.startsWith("/my")}
                  asChild
                  className={cn(
                    "transition-all",
                    pathname.startsWith("/my") && ACTIVE_ITEM_CLASS,
                  )}
                >
                  <RouterLink to="/my/exams" onClick={handleMenuClick}>
                    <GraduationCap />
                    <span>我的成绩</span>
                  </RouterLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroup>
        ) : isPlatform ? (
          <SidebarGroup>
            <SidebarGroupLabel className="text-sidebar-foreground/50">
              平台管理
            </SidebarGroupLabel>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  tooltip="学校管理"
                  isActive={
                    pathname.startsWith("/platform") &&
                    !pathname.startsWith("/platform/settings")
                  }
                  asChild
                  className={cn(
                    "transition-all",
                    pathname.startsWith("/platform") &&
                      !pathname.startsWith("/platform/settings") &&
                      ACTIVE_ITEM_CLASS,
                  )}
                >
                  {/* /platform 路由由平台组并行开发中，routeTree 尚未注册，暂用断言绕过类型检查 */}
                  <RouterLink to="/platform" onClick={handleMenuClick}>
                    <Building2 />
                    <span>学校管理</span>
                  </RouterLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
              {isPlatformSuperuser && (
                <SidebarMenuItem>
                  <SidebarMenuButton
                    tooltip="系统设置"
                    isActive={pathname.startsWith("/platform/settings")}
                    asChild
                    className={cn(
                      "transition-all",
                      pathname.startsWith("/platform/settings") &&
                        ACTIVE_ITEM_CLASS,
                    )}
                  >
                    <RouterLink
                      to="/platform/settings"
                      onClick={handleMenuClick}
                    >
                      <Settings2 />
                      <span>系统设置</span>
                    </RouterLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              )}
            </SidebarMenu>
          </SidebarGroup>
        ) : (
          <>
            <SidebarGroup>
              <SidebarGroupLabel className="text-sidebar-foreground/50">
                阅卷工作区
              </SidebarGroupLabel>
              <SidebarMenu>
                {MAIN_ITEMS.map((item) => {
                  const active = isItemActive(item, currentExamId, pathname)
                  return (
                    <SidebarMenuItem key={item.title}>
                      <SidebarMenuButton
                        tooltip={item.title}
                        isActive={active}
                        asChild
                        className={cn(
                          "transition-all",
                          active && ACTIVE_ITEM_CLASS,
                        )}
                      >
                        <RouterLink
                          to={item.to(currentExamId)}
                          onClick={handleMenuClick}
                        >
                          <item.icon />
                          <span>{item.title}</span>
                        </RouterLink>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  )
                })}
              </SidebarMenu>
            </SidebarGroup>
            <SidebarGroup>
              <SidebarGroupLabel className="text-sidebar-foreground/50">
                管理
              </SidebarGroupLabel>
              <SidebarMenu>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    tooltip="班级学生"
                    isActive={pathname.startsWith("/classes")}
                    asChild
                    className={cn(
                      "transition-all",
                      pathname.startsWith("/classes") && ACTIVE_ITEM_CLASS,
                    )}
                  >
                    <RouterLink to="/classes" onClick={handleMenuClick}>
                      <Users />
                      <span>班级学生</span>
                    </RouterLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    tooltip="高级设置"
                    isActive={pathname.startsWith("/advanced-settings")}
                    asChild
                    className={cn(
                      "transition-all",
                      pathname.startsWith("/advanced-settings") &&
                        ACTIVE_ITEM_CLASS,
                    )}
                  >
                    <RouterLink
                      to="/advanced-settings"
                      onClick={handleMenuClick}
                    >
                      <Settings2 />
                      <span>高级设置</span>
                    </RouterLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
                {isSchoolAdmin && (
                  <>
                    <SidebarMenuItem>
                      <SidebarMenuButton
                        tooltip="用户管理"
                        isActive={pathname.startsWith("/admin")}
                        asChild
                        className={cn(
                          "transition-all",
                          pathname.startsWith("/admin") && ACTIVE_ITEM_CLASS,
                        )}
                      >
                        <RouterLink to="/admin" onClick={handleMenuClick}>
                          <ShieldCheck />
                          <span>用户管理</span>
                        </RouterLink>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                    <SidebarMenuItem>
                      <SidebarMenuButton
                        tooltip="学校设置"
                        isActive={pathname.startsWith("/org-settings")}
                        asChild
                        className={cn(
                          "transition-all",
                          pathname.startsWith("/org-settings") &&
                            ACTIVE_ITEM_CLASS,
                        )}
                      >
                        <RouterLink
                          to="/org-settings"
                          onClick={handleMenuClick}
                        >
                          <Settings2 />
                          <span>学校设置</span>
                        </RouterLink>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  </>
                )}
              </SidebarMenu>
            </SidebarGroup>
          </>
        )}
      </SidebarContent>
      <SidebarFooter className="gap-1 border-t border-sidebar-border">
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
