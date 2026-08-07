import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowLeft } from "lucide-react"
import { Suspense } from "react"

import { PlatformService } from "@/client"
import { resolveRole } from "@/components/Admin/roleMeta"
import { PageHead } from "@/components/Common/PageHead"
import { Tag } from "@/components/Common/Tag"
import { OrgBillingCard } from "@/components/Platform/OrgBillingCard"
import { OrgInfoCard } from "@/components/Platform/OrgInfoCard"
import { OrgModelUsageSection } from "@/components/Platform/OrgModelUsageSection"
import { OrgStatsCards } from "@/components/Platform/OrgStatsCards"
import {
  ORG_STATUS_LABELS,
  ORG_STATUS_TAG_VARIANTS,
  requirePlatformRole,
} from "@/components/Platform/orgMeta"
import { OrgPeopleDirectory } from "@/components/Platform/PeopleDirectory"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import useAuth from "@/hooks/useAuth"

function getOrgQueryOptions(orgId: string) {
  return {
    queryFn: () => PlatformService.readOrg({ orgId }),
    queryKey: ["platform-org", orgId],
  }
}

export const Route = createFileRoute("/_layout/platform_/$orgId")({
  component: PlatformOrgDetail,
  beforeLoad: requirePlatformRole,
  head: () => ({
    meta: [
      {
        title: "学校详情 - 点凡阅卷",
      },
    ],
  }),
})

function OrgDetailContent({ orgId }: { orgId: string }) {
  const { user: currentUser } = useAuth()
  const { data: org } = useSuspenseQuery(getOrgQueryOptions(orgId))
  const canManagePlatform = currentUser
    ? ["platform_superuser", "platform_admin"].includes(
        resolveRole(currentUser),
      )
    : false

  return (
    <div className="flex flex-col gap-6">
      <PageHead
        title={org.name}
        subtitle={`学校代码：${org.code}`}
        actions={
          <div className="flex items-center gap-2.5">
            <Tag variant={ORG_STATUS_TAG_VARIANTS[org.status] ?? "indigo"}>
              {ORG_STATUS_LABELS[org.status] ?? org.status}
            </Tag>
            <Button variant="ghost" size="sm" asChild>
              <Link to="/platform">
                <ArrowLeft />
                学校管理
              </Link>
            </Button>
          </div>
        }
      />
      <OrgStatsCards org={org} />
      <OrgPeopleDirectory orgId={orgId} canAddOwner={canManagePlatform} />
      <OrgBillingCard orgId={orgId} canEdit={canManagePlatform} />
      <OrgModelUsageSection orgId={orgId} />
      <OrgInfoCard org={org} canEdit={canManagePlatform} />
    </div>
  )
}

function OrgDetailSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-2">
        <Skeleton className="h-7 w-48" />
        <Skeleton className="h-4 w-32" />
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-36 rounded-2xl" />
        ))}
      </div>
      <Skeleton className="h-56 rounded-2xl" />
      <Skeleton className="h-64 rounded-2xl" />
    </div>
  )
}

function PlatformOrgDetail() {
  const { orgId } = Route.useParams()

  return (
    <Suspense fallback={<OrgDetailSkeleton />}>
      <OrgDetailContent orgId={orgId} />
    </Suspense>
  )
}
