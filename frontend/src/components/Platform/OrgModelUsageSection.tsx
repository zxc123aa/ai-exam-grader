import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Activity, ArrowRight } from "lucide-react"

import { PlatformService } from "@/client"
import {
  UsageRecords,
  UsageSummaryBand,
} from "@/components/Platform/ModelUsageUI"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"

export function OrgModelUsageSection({ orgId }: { orgId: string }) {
  const overviewQuery = useQuery({
    queryKey: ["platform-model-usage-overview", 30, orgId],
    queryFn: () => PlatformService.readModelUsageOverview({ days: 30, orgId }),
  })
  const recordsQuery = useQuery({
    queryKey: ["platform-model-usage-events", orgId, 30, 0, 8],
    queryFn: () =>
      PlatformService.listModelUsageEvents({
        days: 30,
        orgId,
        offset: 0,
        limit: 8,
      }),
  })
  const overview = overviewQuery.data
  const records = recordsQuery.data

  return (
    <section
      className="overflow-hidden rounded-[10px] border bg-card"
      data-testid="platform-org-model-usage"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <div>
          <div className="flex items-center gap-2">
            <Activity className="size-4 text-muted-foreground" />
            <h2 className="font-semibold">模型调用</h2>
          </div>
          <p className="mt-1 text-muted-foreground text-xs">
            最近 30 天的调用质量、用量和平台成本
          </p>
        </div>
        <Button variant="ghost" size="sm" asChild>
          <Link to="/platform/usage" search={{ orgId, days: 30, page: 1 }}>
            查看全部
            <ArrowRight />
          </Link>
        </Button>
      </div>
      {overviewQuery.isPending || !overview ? (
        <Skeleton className="h-36 rounded-none border-t" />
      ) : (
        <UsageSummaryBand summary={overview.summary} />
      )}
      <div className="flex items-center justify-between border-b px-5 py-3">
        <h3 className="font-semibold text-sm">最近调用</h3>
        <span className="text-muted-foreground text-xs">
          30 天共 {records?.count ?? 0} 条
        </span>
      </div>
      {recordsQuery.isPending || !records ? (
        <Skeleton className="h-64 rounded-none" />
      ) : (
        <UsageRecords rows={records.data} showOrganization={false} />
      )}
    </section>
  )
}
