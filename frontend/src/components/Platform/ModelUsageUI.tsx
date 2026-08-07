import type {
  PlatformModelUsageBreakdownItem,
  PlatformModelUsageEventPublic,
  PlatformModelUsageSummaryPublic,
  UsageReconciliationStatus,
} from "@/client"
import { Tag } from "@/components/Common/Tag"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

export function formatUsageNumber(value = 0, maximumFractionDigits = 2) {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits }).format(value)
}

export function formatUsageDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value))
}

export function formatLatency(value = 0) {
  return value >= 1_000
    ? `${formatUsageNumber(value / 1_000, 1)} 秒`
    : `${formatUsageNumber(value, 0)} ms`
}

export function formatUsageCost(value = 0, detailed = false) {
  return new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: detailed && Math.abs(value) < 1 ? 4 : 2,
    maximumFractionDigits: detailed ? 6 : 2,
  }).format(value)
}

const STATUS_META = {
  succeeded: { label: "成功", variant: "mint" as const },
  failed: { label: "失败", variant: "red" as const },
  missing_usage: { label: "用量待补", variant: "amber" as const },
}

const RECONCILIATION_META: Record<
  UsageReconciliationStatus,
  { label: string; variant: "neutral" | "mint" | "amber" | "red" }
> = {
  pending: { label: "待同步账单", variant: "neutral" },
  matched: { label: "账单一致", variant: "mint" },
  mismatch: { label: "费用有差异", variant: "amber" },
  missing_upstream: { label: "上游缺记录", variant: "red" },
  missing_local: { label: "本地缺记录", variant: "red" },
}

export function UsageSummaryBand({
  summary,
}: {
  summary: PlatformModelUsageSummaryPublic
}) {
  const hasActualCost = (summary.reconciled_calls ?? 0) > 0
  const calls = summary.calls ?? 0
  const reconciledCalls = summary.reconciled_calls ?? 0
  const coverage = calls ? Math.min(100, (reconciledCalls / calls) * 100) : 0
  const stats = [
    ["调用次数", formatUsageNumber(summary.calls, 0)],
    ["成功率", `${formatUsageNumber((summary.success_rate ?? 0) * 100, 1)}%`],
    ["Token", formatUsageNumber(summary.total_tokens, 0)],
    ["计费积分", formatUsageNumber(summary.customer_credits, 2)],
    [
      hasActualCost ? "上游实付" : "成本估算",
      `¥${formatUsageCost(
        hasActualCost ? summary.upstream_cost_rmb : summary.internal_cost_rmb,
      )}`,
    ],
    ["平均耗时", formatLatency(summary.average_latency_ms)],
  ]
  return (
    <div className="border-b">
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6">
        {stats.map(([label, value], index) => (
          <div
            key={label}
            className={`min-w-0 px-4 py-4 sm:px-5 ${
              index % 2 !== 1 ? "border-r" : ""
            } md:border-r md:nth-[3n]:border-r-0 xl:nth-[3n]:border-r xl:last:border-r-0`}
          >
            <p className="text-muted-foreground text-xs">{label}</p>
            <p className="mt-1 truncate font-semibold text-xl tabular-nums">
              {value}
            </p>
          </div>
        ))}
      </div>
      <div className="grid gap-2 border-t bg-muted/20 px-4 py-3 text-xs sm:grid-cols-[minmax(10rem,1fr)_auto] sm:items-center sm:px-5">
        <div className="flex min-w-0 items-center gap-3">
          <span className="shrink-0 font-medium">账单覆盖</span>
          <div className="h-1.5 min-w-16 flex-1 overflow-hidden rounded-full bg-border">
            <div
              className="h-full bg-primary"
              style={{ width: `${coverage}%` }}
            />
          </div>
          <span className="shrink-0 text-muted-foreground tabular-nums">
            {reconciledCalls} / {calls} 次
          </span>
        </div>
        <p className="text-muted-foreground tabular-nums sm:text-right">
          已核对调用估算 ¥
          {formatUsageCost(summary.reconciled_internal_cost_rmb)} · 差额{" "}
          <span
            className={
              Math.abs(summary.cost_variance_rmb ?? 0) > 0.000001
                ? "text-amber-700 dark:text-amber-400"
                : "text-foreground"
            }
          >
            {(summary.cost_variance_rmb ?? 0) > 0 ? "+" : ""}¥
            {formatUsageCost(summary.cost_variance_rmb)}
          </span>
        </p>
      </div>
    </div>
  )
}

export function UsageBreakdownTable({
  title,
  rows,
  onSelect,
}: {
  title: string
  rows: PlatformModelUsageBreakdownItem[]
  onSelect?: (row: PlatformModelUsageBreakdownItem) => void
}) {
  return (
    <div className="min-w-0 px-5 py-5">
      <h3 className="mb-3 font-semibold text-sm">{title}</h3>
      {rows.length === 0 ? (
        <p className="py-8 text-center text-muted-foreground text-sm">
          暂无调用
        </p>
      ) : (
        <div className="space-y-1">
          {rows.slice(0, 8).map((row, index) => (
            <button
              key={row.key}
              type="button"
              disabled={!onSelect}
              onClick={() => onSelect?.(row)}
              className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-md px-2 py-2 text-left enabled:hover:bg-muted/60 disabled:cursor-default"
            >
              <div className="min-w-0">
                <p className="truncate font-medium text-sm">
                  <span className="mr-2 text-muted-foreground tabular-nums">
                    {index + 1}
                  </span>
                  {row.label}
                </p>
                <p className="mt-0.5 truncate text-muted-foreground text-xs">
                  {formatUsageNumber(row.total_tokens, 0)} token ·{" "}
                  {row.reconciled_calls
                    ? `¥${formatUsageCost(row.upstream_cost_rmb)} 实付`
                    : `¥${formatUsageCost(row.internal_cost_rmb)} 估算`}
                </p>
              </div>
              <div className="text-right">
                <p className="font-medium text-sm tabular-nums">
                  {formatUsageNumber(row.calls, 0)} 次
                </p>
                <p className="text-muted-foreground text-xs tabular-nums">
                  {row.failed_calls ? `${row.failed_calls} 次失败` : "全部成功"}
                </p>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function UsageStatus({
  status,
}: {
  status: PlatformModelUsageEventPublic["status"]
}) {
  const meta = STATUS_META[status]
  return <Tag variant={meta.variant}>{meta.label}</Tag>
}

function ReconciliationStatus({
  status,
}: {
  status: UsageReconciliationStatus
}) {
  const meta = RECONCILIATION_META[status]
  return <Tag variant={meta.variant}>{meta.label}</Tag>
}

function UsageCost({
  row,
  align = "right",
}: {
  row: PlatformModelUsageEventPublic
  align?: "left" | "right"
}) {
  const hasActual =
    row.upstream_cost_rmb !== null && row.upstream_cost_rmb !== undefined
  const variance = row.cost_variance_rmb ?? 0
  return (
    <div className={align === "right" ? "text-right" : "text-left"}>
      <p className="font-medium tabular-nums">
        {hasActual
          ? `实付 ¥${formatUsageCost(row.upstream_cost_rmb ?? 0, true)}`
          : `估算 ¥${formatUsageCost(row.internal_cost_rmb, true)}`}
      </p>
      {hasActual && (
        <>
          <p className="text-muted-foreground text-xs tabular-nums">
            估算 ¥{formatUsageCost(row.internal_cost_rmb, true)}
          </p>
          <p
            className={`text-xs tabular-nums ${
              Math.abs(variance) > 0.000001
                ? "text-amber-700 dark:text-amber-400"
                : "text-muted-foreground"
            }`}
          >
            差额 {variance > 0 ? "+" : ""}¥{formatUsageCost(variance, true)}
          </p>
        </>
      )}
    </div>
  )
}

export function UsageRecords({
  rows,
  showOrganization = true,
}: {
  rows: PlatformModelUsageEventPublic[]
  showOrganization?: boolean
}) {
  if (rows.length === 0) {
    return (
      <p className="px-5 py-12 text-center text-muted-foreground text-sm">
        当前筛选条件下没有调用记录
      </p>
    )
  }
  return (
    <>
      <div className="hidden md:block">
        <Table className="min-w-[980px]">
          <TableHeader>
            <TableRow>
              <TableHead>时间</TableHead>
              {showOrganization && <TableHead>学校</TableHead>}
              <TableHead>功能</TableHead>
              <TableHead>实际模型 / 通道</TableHead>
              <TableHead className="text-right">Token</TableHead>
              <TableHead className="text-right">耗时</TableHead>
              <TableHead className="text-right">积分</TableHead>
              <TableHead className="text-right">上游费用</TableHead>
              <TableHead>调用 / 对账</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="text-muted-foreground">
                  {formatUsageDate(row.created_at)}
                </TableCell>
                {showOrganization && (
                  <TableCell className="max-w-44 truncate font-medium">
                    {row.org_name}
                  </TableCell>
                )}
                <TableCell>{row.purpose_label}</TableCell>
                <TableCell>
                  <p className="max-w-56 truncate font-medium">
                    {row.actual_model ?? row.requested_model}
                  </p>
                  <p className="max-w-56 truncate text-muted-foreground text-xs">
                    {row.channel_name ?? row.actual_provider ?? "未记录通道"}
                    {row.fallback_used ? " · 已回退" : ""}
                  </p>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatUsageNumber(row.total_tokens, 0)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatLatency(row.latency_ms)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatUsageNumber(row.customer_credits, 3)}
                </TableCell>
                <TableCell>
                  <UsageCost row={row} />
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    <UsageStatus status={row.status} />
                    <ReconciliationStatus status={row.reconciliation_status} />
                  </div>
                  {row.error_code && (
                    <p className="mt-1 max-w-32 truncate text-destructive text-xs">
                      {row.error_code}
                    </p>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <div className="divide-y md:hidden">
        {rows.map((row) => (
          <article key={row.id} className="px-4 py-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate font-medium text-sm">
                  {row.purpose_label} ·{" "}
                  {row.actual_model ?? row.requested_model}
                </p>
                <p className="mt-1 truncate text-muted-foreground text-xs">
                  {showOrganization ? `${row.org_name} · ` : ""}
                  {row.channel_name ?? row.actual_provider ?? "未记录通道"}
                </p>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1">
                <UsageStatus status={row.status} />
                <ReconciliationStatus status={row.reconciliation_status} />
              </div>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
              <span className="text-muted-foreground">
                {formatUsageDate(row.created_at)}
              </span>
              <span className="text-right tabular-nums">
                {formatUsageNumber(row.total_tokens, 0)} token
              </span>
              <span className="text-muted-foreground">
                {formatLatency(row.latency_ms)}
              </span>
              <span className="text-right tabular-nums">
                {formatUsageNumber(row.customer_credits, 3)} 积分
              </span>
            </div>
            <div className="mt-2 border-t pt-2 text-xs">
              <UsageCost row={row} />
            </div>
          </article>
        ))}
      </div>
    </>
  )
}
