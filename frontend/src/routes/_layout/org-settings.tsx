import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, redirect } from "@tanstack/react-router"
import { useEffect, useState } from "react"

import { OrgService, UsersService } from "@/client"
import { resolveRole } from "@/components/Admin/roleMeta"
import { PageHead } from "@/components/Common/PageHead"
import { OrgBillingSection } from "@/components/Org/OrgBillingSection"
import { OrgModelSettingsSection } from "@/components/Org/OrgModelSettingsSection"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import { Skeleton } from "@/components/ui/skeleton"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

/** 学校管理者（与侧栏「学校设置」入口一致）才能进入学校设置页。 */
const SCHOOL_ROLES = ["school_owner", "school_admin"]

export const Route = createFileRoute("/_layout/org-settings")({
  component: OrgSettings,
  beforeLoad: async () => {
    const user = await UsersService.readUserMe()
    if (!SCHOOL_ROLES.includes(resolveRole(user))) {
      throw redirect({
        to: "/",
      })
    }
  },
  head: () => ({
    meta: [
      {
        title: "学校设置 - 点凡阅卷",
      },
    ],
  }),
})

const CARD_CLASS = "rounded-2xl bg-card p-6 shadow-card"

function OrgSettings() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  // 仅总管理员可编辑；其他学校角色只读查看
  const canEdit = user ? resolveRole(user) === "school_owner" : false

  const { data: settings, isPending } = useQuery({
    queryKey: ["org-settings"],
    queryFn: () => OrgService.readOrgSettings(),
  })

  const [contactName, setContactName] = useState("")
  const [sharingEnabled, setSharingEnabled] = useState(false)

  useEffect(() => {
    if (settings) {
      setContactName(settings.contact_name ?? "")
      setSharingEnabled(settings.exam_sharing_enabled)
    }
  }, [settings])

  const mutation = useMutation({
    mutationFn: () =>
      OrgService.updateOrgSettings({
        requestBody: {
          contact_name: contactName.trim() || null,
          exam_sharing_enabled: sharingEnabled,
        },
      }),
    onSuccess: () => {
      showSuccessToast("学校设置已保存")
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["org-settings"] })
    },
  })

  if (isPending || !settings) {
    return (
      <div className="flex flex-col gap-6">
        <PageHead
          title="学校设置"
          subtitle="查看与维护本校的基本信息和协作设置"
        />
        <Skeleton className="h-44 rounded-2xl" />
        <Skeleton className="h-32 rounded-2xl" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6" data-testid="org-settings-page">
      <PageHead
        title="学校设置"
        subtitle="查看与维护本校的基本信息和协作设置"
      />

      {!canEdit && (
        <p
          className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-700 text-sm dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-400"
          data-testid="org-settings-readonly-hint"
        >
          仅总管理员可以修改学校设置，当前为只读查看。
        </p>
      )}

      <OrgBillingSection />

      <OrgModelSettingsSection canEdit={canEdit} />

      <section className={CARD_CLASS}>
        <h3 className="font-semibold">学校信息</h3>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div className="grid gap-1.5">
            <Label htmlFor="org-name">学校名称</Label>
            <Input id="org-name" value={settings.name} disabled />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="org-code">学校代码</Label>
            <Input id="org-code" value={settings.code} disabled />
          </div>
          <div className="grid gap-1.5 sm:col-span-2">
            <Label htmlFor="org-contact">联系人</Label>
            <Input
              id="org-contact"
              data-testid="org-contact-input"
              placeholder="请输入学校联系人姓名"
              value={contactName}
              onChange={(e) => setContactName(e.target.value)}
              disabled={!canEdit}
            />
          </div>
        </div>
      </section>

      <section className={CARD_CLASS}>
        <h3 className="font-semibold">协作设置</h3>
        <label
          className="mt-4 flex items-start gap-3"
          htmlFor="exam-sharing-enabled"
        >
          <Checkbox
            id="exam-sharing-enabled"
            data-testid="exam-sharing-switch"
            className="mt-0.5"
            checked={sharingEnabled}
            onCheckedChange={(checked) => setSharingEnabled(checked === true)}
            disabled={!canEdit}
          />
          <span className="grid gap-1">
            <span className="font-medium text-sm">教师间考试互相可见</span>
            <span className="text-muted-foreground text-sm">
              开启后，同校老师可以只读查看彼此的考试。
            </span>
          </span>
        </label>
      </section>

      {canEdit && (
        <div>
          <LoadingButton
            data-testid="org-settings-save"
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            保存设置
          </LoadingButton>
        </div>
      )}
    </div>
  )
}

export default OrgSettings
