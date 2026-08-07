import { useQuery } from "@tanstack/react-query"
import { Coins } from "lucide-react"

import { OrgService } from "@/client"
import { Tag } from "@/components/Common/Tag"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

const STATUS_LABELS = {
  available: "服务可用",
  insufficient: "积分不足",
  expired: "合同已到期",
  not_configured: "尚未开通",
} as const

const WORKFLOW_LABELS: Record<string, string> = {
  answer_extraction: "答题识别",
  answer_recognition: "答题识别",
  subjective_grading: "主观题批改",
  rubric_question_recognition: "题目识别",
  rubric_generation: "参考答案生成",
  rubric_validation: "参考答案校验",
  question_recognition: "题目识别",
  answer_preparation: "参考答案生成",
}

function formatNumber(value = 0, maximumFractionDigits = 2) {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits }).format(value)
}

export function OrgBillingSection() {
  const summaryQuery = useQuery({
    queryKey: ["org-billing-summary"],
    queryFn: () => OrgService.readBillingSummary(),
  })
  const usageQuery = useQuery({
    queryKey: ["org-billing-usage"],
    queryFn: () => OrgService.readBillingUsage({ offset: 0, limit: 12 }),
  })

  if (summaryQuery.isPending || !summaryQuery.data) {
    return <Skeleton className="h-72 rounded-[10px]" />
  }

  const summary = summaryQuery.data
  const subscription = summary.subscription

  return (
    <section
      className="overflow-hidden rounded-[10px] border border-border bg-card"
      data-testid="org-billing-section"
    >
      <div className="flex flex-wrap items-start justify-between gap-4 px-6 py-5">
        <div>
          <div className="flex items-center gap-2">
            <Coins className="size-4 text-muted-foreground" />
            <h2 className="font-semibold">服务额度</h2>
            <Tag
              variant={summary.entitlement === "available" ? "mint" : "amber"}
            >
              {STATUS_LABELS[summary.entitlement]}
            </Tag>
          </div>
          <p className="mt-3 font-semibold text-3xl tabular-nums">
            {formatNumber(summary.available_credits)}
            <span className="ml-2 font-normal text-muted-foreground text-sm">
              可用积分
            </span>
          </p>
        </div>
        <p className="text-right text-muted-foreground text-sm">
          {subscription
            ? `有效期至 ${new Date(subscription.ends_at).toLocaleDateString("zh-CN")}`
            : "请联系点凡阅卷开通服务"}
        </p>
      </div>

      <dl className="grid border-y bg-muted/20 sm:grid-cols-2">
        {[
          ["已预留", formatNumber(summary.reserved_credits)],
          ["已使用", formatNumber(summary.consumed_credits)],
        ].map(([label, value], index) => (
          <div
            key={label}
            className={`px-5 py-4 ${index ? "border-t sm:border-t-0 sm:border-l" : ""}`}
          >
            <dt className="text-muted-foreground text-xs">{label}</dt>
            <dd className="mt-1 font-medium text-sm tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>

      <div className="px-6 py-5">
        <h3 className="font-medium text-sm">最近使用</h3>
        {usageQuery.data?.data.length ? (
          <div className="mt-3 overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>时间</TableHead>
                  <TableHead>用途</TableHead>
                  <TableHead className="text-right">积分</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {usageQuery.data.data.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {new Date(item.created_at).toLocaleString("zh-CN")}
                    </TableCell>
                    <TableCell>
                      {WORKFLOW_LABELS[item.workflow_purpose] ?? "自动处理"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatNumber(item.credits, 4)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="mt-3 text-muted-foreground text-sm">暂无使用记录</p>
        )}
      </div>
    </section>
  )
}
