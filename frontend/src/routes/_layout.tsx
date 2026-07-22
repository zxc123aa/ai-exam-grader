import {
  createFileRoute,
  Link,
  Outlet,
  redirect,
  useRouterState,
} from "@tanstack/react-router"
import { ChevronRight } from "lucide-react"
import { Fragment } from "react"

import { Footer } from "@/components/Common/Footer"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import { Separator } from "@/components/ui/separator"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { isLoggedIn } from "@/hooks/useAuth"

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

const SEGMENT_LABELS: Record<string, string> = {
  exams: "考试管理",
  marking: "区域校正",
  questions: "识别内容",
  answers: "标准答案",
  grading: "批量批改",
  submissions: "学生答卷",
  review: "人工复核",
  admin: "用户管理",
  settings: "个人设置",
}

function Breadcrumbs() {
  const { location } = useRouterState()
  const segments = location.pathname.split("/").filter(Boolean)
  const crumbs = [
    { label: "工作台", to: "/" },
    ...segments
      .map((segment, index) => {
        const label = SEGMENT_LABELS[segment]
        if (!label) return null
        return {
          label,
          to: `/${segments.slice(0, index + 1).join("/")}`,
        }
      })
      .filter((item): item is { label: string; to: string } => Boolean(item)),
  ]

  return (
    <nav className="flex min-w-0 items-center gap-1.5 text-sm">
      {crumbs.map((crumb, index) => {
        const isLast = index === crumbs.length - 1
        return (
          <Fragment key={`${crumb}-${index}`}>
            {index > 0 && (
              <ChevronRight className="size-3.5 shrink-0 text-muted-foreground/60" />
            )}
            {isLast ? (
              <span className="truncate font-medium text-foreground">
                {crumb.label}
              </span>
            ) : (
              <Link
                to={crumb.to as never}
                className="truncate rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {crumb.label}
              </Link>
            )}
          </Fragment>
        )
      })}
    </nav>
  )
}

function Layout() {
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/70">
          <SidebarTrigger className="-ml-1 text-muted-foreground" />
          <Separator orientation="vertical" className="!h-4" />
          <Breadcrumbs />
        </header>
        <main className="flex-1 p-6 md:p-8">
          <div className="mx-auto max-w-7xl">
            <Outlet />
          </div>
        </main>
        <Footer />
      </SidebarInset>
    </SidebarProvider>
  )
}

export default Layout
