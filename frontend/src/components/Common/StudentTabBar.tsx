import { Link as RouterLink } from "@tanstack/react-router"
import { BookMarked, GraduationCap, Network, UserRound } from "lucide-react"
import { cn } from "@/lib/utils"

const TABS = [
  { to: "/my/exams", label: "成绩", icon: GraduationCap, match: "/my/exams" },
  {
    to: "/my/wrongbook",
    label: "错题本",
    icon: BookMarked,
    match: "/my/wrongbook",
  },
  { to: "/my/knowledge", label: "图谱", icon: Network, match: "/my/knowledge" },
  { to: "/settings", label: "我的", icon: UserRound, match: "/settings" },
] as const

/**
 * 学生端移动底部导航。
 *
 * 学生基本都在手机上打开，桌面侧栏折叠成左上角汉堡后没人会去点，因此小屏改用
 * 底部 tab；桌面维持侧栏（`md:hidden`）。
 */
export function StudentTabBar({ pathname }: { pathname: string }) {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-20 flex border-t bg-background/95 backdrop-blur md:hidden print:hidden">
      {TABS.map((tab) => {
        const active = pathname.startsWith(tab.match)
        const Icon = tab.icon
        return (
          <RouterLink
            key={tab.to}
            to={tab.to}
            className={cn(
              "flex flex-1 flex-col items-center gap-0.5 py-2.5 text-[11px] transition-colors",
              active ? "text-primary" : "text-muted-foreground",
            )}
          >
            <Icon className="size-5" />
            {tab.label}
          </RouterLink>
        )
      })}
    </nav>
  )
}
