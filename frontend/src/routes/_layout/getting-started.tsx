import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link, redirect } from "@tanstack/react-router"
import {
  Check,
  Clipboard,
  GraduationCap,
  School,
  Upload,
  UserRoundPlus,
  UsersRound,
} from "lucide-react"

import {
  type OrganizationSignupCompleted,
  OrgService,
  UsersService,
} from "@/client"
import { resolveRole } from "@/components/Admin/roleMeta"
import { PageHead } from "@/components/Common/PageHead"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { cn } from "@/lib/utils"

export const Route = createFileRoute("/_layout/getting-started")({
  component: GettingStarted,
  beforeLoad: async () => {
    const user = await UsersService.readUserMe()
    if (resolveRole(user) !== "school_owner") throw redirect({ to: "/" })
  },
  head: () => ({ meta: [{ title: "首次开通 - 点凡阅卷" }] }),
})

function signupResult() {
  try {
    const value = sessionStorage.getItem("dianfan-signup-result")
    return value ? (JSON.parse(value) as OrganizationSignupCompleted) : null
  } catch {
    return null
  }
}

function GettingStarted() {
  const { logout } = useAuth()
  const { showSuccessToast } = useCustomToast()
  const settings = useQuery({
    queryKey: ["org-settings"],
    queryFn: () => OrgService.readOrgSettings(),
  })
  const onboarding = useQuery({
    queryKey: ["org-onboarding"],
    queryFn: () => OrgService.readOrgOnboarding(),
  })
  const result = signupResult()

  if (settings.isPending || onboarding.isPending) {
    return (
      <div className="grid gap-5">
        <Skeleton className="h-20 rounded-lg" />
        <Skeleton className="h-96 rounded-lg" />
      </div>
    )
  }
  if (!settings.data || !onboarding.data) return null

  const data = onboarding.data
  const steps = [
    {
      title: "创建班级",
      description: "先建立本次内测涉及的年级和班级。",
      count: data.class_count,
      countLabel: "个班级",
      done: data.class_count > 0,
      icon: School,
      action: (
        <Button size="sm" variant="outline" asChild>
          <Link to="/classes">管理班级</Link>
        </Button>
      ),
    },
    {
      title: "导入老师花名册",
      description: "批量粘贴或上传 CSV，导入后会生成老师账号。",
      count: data.teacher_count,
      countLabel: "位老师",
      done: data.teacher_count > 0,
      icon: UserRoundPlus,
      action: (
        <Button size="sm" variant="outline" asChild>
          <Link to="/admin">导入老师</Link>
        </Button>
      ),
    },
    {
      title: "导入学生花名册",
      description: "进入班级后导入学生姓名和学号，可按需创建登录账号。",
      count: data.student_count,
      countLabel: "名学生",
      done: data.student_count > 0,
      icon: UsersRound,
      action: (
        <Button size="sm" variant="outline" asChild>
          <Link to="/classes">导入学生</Link>
        </Button>
      ),
    },
    {
      title: "用老师账号完成一次试批",
      description:
        "退出总管理员账号，使用导入的老师邮箱和初始密码登录，再创建考试并上传答卷。",
      count: data.teacher_exam_count,
      countLabel: "场老师考试",
      done: data.teacher_exam_count > 0,
      icon: Upload,
      action:
        data.teacher_exam_count > 0 ? (
          <Button size="sm" asChild>
            <Link to="/">进入工作台</Link>
          </Button>
        ) : (
          <Button
            size="sm"
            onClick={logout}
            disabled={data.teacher_count === 0}
          >
            用老师账号登录
          </Button>
        ),
    },
  ]
  const completed = steps.filter((step) => step.done).length

  return (
    <div className="flex flex-col gap-5" data-testid="getting-started-page">
      <PageHead
        title="学校已开通"
        subtitle="按下面的顺序准备名册，再用老师账号完成第一次批卷"
        actions={
          <Button variant="ghost" asChild>
            <Link to="/">暂时跳过</Link>
          </Button>
        }
      />

      <section className="overflow-hidden rounded-lg border bg-card">
        <div className="grid gap-4 border-b bg-muted/20 px-5 py-4 sm:grid-cols-[1fr_auto] sm:items-center">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <GraduationCap className="size-4 text-primary" />
              <h2 className="truncate font-semibold">{settings.data.name}</h2>
            </div>
            <p className="mt-1 text-muted-foreground text-xs">
              {result
                ? `内测至 ${new Date(result.trial_ends_at).toLocaleDateString("zh-CN")} · ${result.answer_quota} 份答卷额度`
                : "30 天内测 · 200 份答卷额度"}
            </p>
          </div>
          <button
            type="button"
            className="flex h-9 items-center justify-between gap-4 rounded-md border bg-background px-3 font-mono text-sm sm:min-w-48"
            onClick={async () => {
              await navigator.clipboard.writeText(settings.data.code)
              showSuccessToast("学校 ID 已复制")
            }}
            title="复制学校 ID"
          >
            <span>
              <span className="mr-2 font-sans text-muted-foreground text-xs">
                学校 ID
              </span>
              {settings.data.code}
            </span>
            <Clipboard className="size-4 text-muted-foreground" />
          </button>
        </div>

        <div className="flex items-center justify-between border-b px-5 py-3 text-sm">
          <span className="font-medium">开通进度</span>
          <span className="text-muted-foreground tabular-nums">
            {completed} / {steps.length}
          </span>
        </div>

        <ol className="divide-y">
          {steps.map((step, index) => (
            <li
              key={step.title}
              className="grid gap-4 px-5 py-4 sm:grid-cols-[40px_1fr_auto] sm:items-center"
            >
              <span
                className={cn(
                  "flex size-9 items-center justify-center rounded-md border font-semibold text-sm",
                  step.done
                    ? "border-green-200 bg-green-50 text-green-700"
                    : "bg-muted/30 text-muted-foreground",
                )}
              >
                {step.done ? <Check className="size-4" /> : index + 1}
              </span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <step.icon className="size-4 text-muted-foreground" />
                  <h3 className="font-medium text-sm">{step.title}</h3>
                  <span className="text-muted-foreground text-xs tabular-nums">
                    {step.count} {step.countLabel}
                  </span>
                </div>
                <p className="mt-1 text-muted-foreground text-xs leading-5">
                  {step.description}
                </p>
              </div>
              <div className="sm:justify-self-end">{step.action}</div>
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}
