import { createFileRoute } from "@tanstack/react-router"

import BasicInfoCard from "@/components/UserSettings/BasicInfoCard"
import ProfileHeaderCard from "@/components/UserSettings/ProfileHeaderCard"
import SecurityCard from "@/components/UserSettings/SecurityCard"
import useAuth from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout/settings")({
  component: UserSettings,
  head: () => ({
    meta: [
      {
        title: "个人设置 - 点凡阅卷",
      },
    ],
  }),
})

function UserSettings() {
  const { user: currentUser } = useAuth()
  if (!currentUser) {
    return null
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">个人设置</h1>
        <p className="text-muted-foreground">管理你的账号信息与偏好设置</p>
      </div>

      <div className="flex max-w-2xl flex-col gap-6">
        <ProfileHeaderCard />
        <BasicInfoCard />
        <SecurityCard />
      </div>
    </div>
  )
}
