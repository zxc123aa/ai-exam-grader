import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { School } from "lucide-react"
import { Suspense } from "react"
import { z } from "zod"

import { PlatformService } from "@/client"
import { resolveRole } from "@/components/Admin/roleMeta"
import { DataTable } from "@/components/Common/DataTable"
import { EmptyState } from "@/components/Common/EmptyState"
import { PageHead } from "@/components/Common/PageHead"
import PendingOrgs from "@/components/Pending/PendingOrgs"
import AddOrg from "@/components/Platform/AddOrg"
import { columns } from "@/components/Platform/columns"
import { requirePlatformRole } from "@/components/Platform/orgMeta"
import { PlatformDirectorySearch } from "@/components/Platform/PeopleDirectory"
import useAuth from "@/hooks/useAuth"

function getOrgsQueryOptions() {
  return {
    queryFn: () => PlatformService.listOrgs(),
    queryKey: ["platform-orgs"],
  }
}

export const Route = createFileRoute("/_layout/platform")({
  component: Platform,
  beforeLoad: requirePlatformRole,
  validateSearch: z.object({
    q: z.string().optional().catch(undefined),
  }),
  head: () => ({
    meta: [
      {
        title: "学校管理 - 点凡阅卷",
      },
    ],
  }),
})

function OrgsTableContent() {
  const { data: orgs } = useSuspenseQuery(getOrgsQueryOptions())

  if (orgs.data.length === 0) {
    return (
      <EmptyState
        icon={School}
        title="还没有学校"
        description="点击右上角「新建学校」创建第一个学校租户"
        className="bg-card shadow-card"
      />
    )
  }

  return <DataTable columns={columns} data={orgs.data} />
}

function Platform() {
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  const { user: currentUser } = useAuth()
  const canManagePlatform = currentUser
    ? ["platform_superuser", "platform_admin"].includes(
        resolveRole(currentUser),
      )
    : false

  return (
    <div className="flex flex-col gap-6">
      <PageHead
        title="学校管理"
        subtitle="从学校进入查看全部账号、老师、班级和学生"
        actions={canManagePlatform ? <AddOrg /> : undefined}
      />
      <PlatformDirectorySearch
        query={search.q ?? ""}
        onQueryChange={(q) =>
          navigate({ search: { q: q || undefined }, replace: true })
        }
      />
      <Suspense fallback={<PendingOrgs />}>
        <OrgsTableContent />
      </Suspense>
    </div>
  )
}
