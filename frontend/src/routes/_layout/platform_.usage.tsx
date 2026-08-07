import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { ChevronLeft, ChevronRight, RefreshCw } from "lucide-react"
import { z } from "zod"

import { type ModelUsageStatus, PlatformService } from "@/client"
import { PageHead } from "@/components/Common/PageHead"
import {
  UsageBreakdownTable,
  UsageRecords,
  UsageSummaryBand,
} from "@/components/Platform/ModelUsageUI"
import { requirePlatformRole } from "@/components/Platform/orgMeta"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"

const searchSchema = z.object({
  days: z.coerce.number().int().min(1).max(365).catch(30),
  orgId: z.string().min(1).optional().catch(undefined),
  purpose: z.string().optional().catch(undefined),
  status: z
    .enum(["succeeded", "failed", "missing_usage"])
    .optional()
    .catch(undefined),
  page: z.coerce.number().int().min(1).catch(1),
})

const PAGE_SIZE = 20

export const Route = createFileRoute("/_layout/platform_/usage")({
  component: PlatformUsagePage,
  beforeLoad: requirePlatformRole,
  validateSearch: searchSchema,
  head: () => ({ meta: [{ title: "调用记录 - 点凡阅卷" }] }),
})

function PlatformUsagePage() {
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  const overviewQuery = useQuery({
    queryKey: ["platform-model-usage-overview", search.days, search.orgId],
    queryFn: () =>
      PlatformService.readModelUsageOverview({
        days: search.days,
        orgId: search.orgId,
      }),
  })
  const recordsQuery = useQuery({
    queryKey: ["platform-model-usage-events", search],
    queryFn: () =>
      PlatformService.listModelUsageEvents({
        days: search.days,
        orgId: search.orgId,
        purpose: search.purpose,
        status: search.status as ModelUsageStatus | undefined,
        offset: (search.page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
  })
  const orgsQuery = useQuery({
    queryKey: ["platform-orgs"],
    queryFn: () => PlatformService.listOrgs(),
  })
  const updateSearch = (updates: Partial<typeof search>) =>
    navigate({ search: { ...search, ...updates } })
  const totalPages = Math.max(
    1,
    Math.ceil((recordsQuery.data?.count ?? 0) / PAGE_SIZE),
  )
  const overview = overviewQuery.data
  const records = recordsQuery.data

  return (
    <div className="flex flex-col gap-6" data-testid="platform-usage-page">
      <PageHead
        title="调用记录"
        subtitle="按学校核对模型用量、稳定性、客户计费与平台成本"
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              overviewQuery.refetch()
              recordsQuery.refetch()
            }}
          >
            <RefreshCw />
            刷新
          </Button>
        }
      />

      <section className="overflow-hidden rounded-[10px] border bg-card">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 sm:px-5">
          <div className="flex rounded-md border bg-muted/30 p-0.5">
            {[7, 30, 90].map((days) => (
              <Button
                key={days}
                type="button"
                size="sm"
                variant={search.days === days ? "default" : "ghost"}
                className="h-7 px-3"
                onClick={() => updateSearch({ days, page: 1 })}
              >
                {days} 天
              </Button>
            ))}
          </div>
          <Select
            value={search.orgId ?? "all"}
            onValueChange={(value) =>
              updateSearch({
                orgId: value === "all" ? undefined : value,
                page: 1,
              })
            }
          >
            <SelectTrigger
              className="w-full sm:w-56"
              data-testid="usage-org-filter"
            >
              <SelectValue placeholder="全部学校" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部学校</SelectItem>
              {orgsQuery.data?.data.map((org) => (
                <SelectItem key={org.id} value={org.id}>
                  {org.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {overviewQuery.isPending || !overview ? (
          <Skeleton className="h-44 rounded-none" />
        ) : (
          <>
            <UsageSummaryBand summary={overview.summary} />
            <div
              className={`grid divide-y lg:divide-x lg:divide-y-0 ${
                search.orgId ? "lg:grid-cols-2" : "lg:grid-cols-3"
              }`}
            >
              {!search.orgId && (
                <UsageBreakdownTable
                  title="学校调用排行"
                  rows={overview.organizations}
                  onSelect={(row) =>
                    updateSearch({ orgId: row.org_id ?? undefined, page: 1 })
                  }
                />
              )}
              <UsageBreakdownTable title="功能分布" rows={overview.purposes} />
              <UsageBreakdownTable title="模型分布" rows={overview.models} />
            </div>
          </>
        )}

        <div className="border-t">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 sm:px-5">
            <div>
              <h2 className="font-semibold">逐次调用</h2>
              <p className="mt-0.5 text-muted-foreground text-xs">
                共 {records?.count ?? 0} 条，按调用时间倒序
              </p>
            </div>
            <div className="flex w-full flex-wrap gap-2 sm:w-auto">
              <Select
                value={search.purpose ?? "all"}
                onValueChange={(value) =>
                  updateSearch({
                    purpose: value === "all" ? undefined : value,
                    page: 1,
                  })
                }
              >
                <SelectTrigger className="min-w-36 flex-1 sm:flex-none">
                  <SelectValue placeholder="全部功能" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部功能</SelectItem>
                  {overview?.purposes.map((row) => (
                    <SelectItem key={row.key} value={row.key}>
                      {row.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={search.status ?? "all"}
                onValueChange={(value) =>
                  updateSearch({
                    status:
                      value === "all" ? undefined : (value as ModelUsageStatus),
                    page: 1,
                  })
                }
              >
                <SelectTrigger className="min-w-32 flex-1 sm:flex-none">
                  <SelectValue placeholder="全部状态" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部状态</SelectItem>
                  <SelectItem value="succeeded">成功</SelectItem>
                  <SelectItem value="failed">失败</SelectItem>
                  <SelectItem value="missing_usage">用量待补</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          {recordsQuery.isPending || !records ? (
            <Skeleton className="h-72 rounded-none" />
          ) : (
            <UsageRecords rows={records.data} />
          )}
          <div className="flex items-center justify-between gap-3 border-t px-4 py-3 text-sm sm:px-5">
            <span className="text-muted-foreground tabular-nums">
              第 {Math.min(search.page, totalPages)} / {totalPages} 页
            </span>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="icon-sm"
                disabled={search.page <= 1}
                onClick={() => updateSearch({ page: search.page - 1 })}
                title="上一页"
              >
                <ChevronLeft />
              </Button>
              <Button
                variant="outline"
                size="icon-sm"
                disabled={search.page >= totalPages}
                onClick={() => updateSearch({ page: search.page + 1 })}
                title="下一页"
              >
                <ChevronRight />
              </Button>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
