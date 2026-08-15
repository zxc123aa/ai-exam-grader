import { createFileRoute, Link } from "@tanstack/react-router"
import { Settings2 } from "lucide-react"
import { resolveRole } from "@/components/Admin/roleMeta"
import { PageHead } from "@/components/Common/PageHead"
import { RunSettingsForm } from "@/components/Common/RunSettingsForm"
import useAuth from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout/advanced-settings")({
  component: AdvancedSettingsPage,
  head: () => ({ meta: [{ title: "高级设置 - 点凡阅卷" }] }),
})

/**
 * 高级设置：给愿意折腾的老师。不想折腾的老师用默认配置即可，
 * 主流程里不展示这些技术参数。
 */
function AdvancedSettingsPage() {
  const { user } = useAuth()
  const role = user ? resolveRole(user) : "teacher"

  return (
    <div className="grid max-w-2xl gap-5">
      <PageHead
        title="高级设置"
        subtitle="模型与批改参数，只对之后发起的批改批次生效；不想改就用默认配置"
      />
      <section className="rounded-2xl border bg-card shadow-card">
        <div className="flex items-center gap-2 border-b px-5 py-3.5">
          <Settings2 className="size-4 text-primary" />
          <h3 className="font-semibold text-sm">批改设置</h3>
        </div>
        <div className="p-5">
          <RunSettingsForm />
        </div>
      </section>
      {role === "platform_superuser" && (
        <p className="text-muted-foreground text-sm">
          平台级的三条管线默认模型在
          <Link
            to="/platform/settings"
            className="ml-1 text-primary hover:underline"
          >
            系统设置
          </Link>
          中维护。
        </p>
      )}
    </div>
  )
}
