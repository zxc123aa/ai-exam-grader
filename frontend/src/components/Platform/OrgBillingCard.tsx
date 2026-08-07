import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CalendarClock, FileCheck2, Plus } from "lucide-react"
import { useEffect, useState } from "react"

import { PlatformService } from "@/client"
import { Tag } from "@/components/Common/Tag"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

const ENTITLEMENT_LABELS = {
  available: "服务可用",
  insufficient: "答卷额度不足",
  expired: "合同已到期",
  not_configured: "尚未开通",
} as const

const ENTRY_LABELS: Record<string, string> = {
  grant: "增加内部预算",
  reserve: "预留模型成本",
  consume: "结算模型成本",
  release: "释放成本预留",
  refund: "退回内部预算",
  adjust: "调整内部预算",
}

function localDateValue(date: Date) {
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

function formatNumber(value = 0) {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(
    value,
  )
}

export function OrgBillingCard({
  orgId,
  canEdit,
}: {
  orgId: string
  canEdit: boolean
}) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [contractOpen, setContractOpen] = useState(false)
  const [grantOpen, setGrantOpen] = useState(false)
  const [contractNo, setContractNo] = useState("")
  const [planCode, setPlanCode] = useState("school-standard")
  const [rateVersionId, setRateVersionId] = useState("")
  const [startsAt, setStartsAt] = useState(localDateValue(new Date()))
  const [endsAt, setEndsAt] = useState(
    localDateValue(new Date(Date.now() + 365 * 24 * 60 * 60 * 1000)),
  )
  const [grantAnswers, setGrantAnswers] = useState("")
  const [grantNote, setGrantNote] = useState("")
  const [riskState, setRiskState] = useState<
    "normal" | "throttled" | "blocked" | "frozen"
  >("normal")
  const [riskReason, setRiskReason] = useState("")
  const [callsPerMinute, setCallsPerMinute] = useState("120")
  const [maxRunningJobs, setMaxRunningJobs] = useState("8")
  const [maxModelConcurrency, setMaxModelConcurrency] = useState("8")
  const [maxJobCredits, setMaxJobCredits] = useState("100")
  const [dailyCreditCap, setDailyCreditCap] = useState("1000")
  const [monthlyCreditCap, setMonthlyCreditCap] = useState("20000")

  const billingQuery = useQuery({
    queryKey: ["platform-org-billing", orgId],
    queryFn: () => PlatformService.readOrgBilling({ orgId }),
  })
  const ledgerQuery = useQuery({
    queryKey: ["platform-org-billing-ledger", orgId],
    queryFn: () =>
      PlatformService.readOrgBillingLedger({ orgId, offset: 0, limit: 8 }),
  })
  const ratesQuery = useQuery({
    queryKey: ["platform-billing-rates"],
    queryFn: () => PlatformService.listBillingRates(),
    enabled: canEdit,
  })
  const policyQuery = useQuery({
    queryKey: ["platform-org-usage-policy", orgId],
    queryFn: () => PlatformService.readOrgUsagePolicy({ orgId }),
  })

  const billing = billingQuery.data
  const rates = ratesQuery.data ?? []

  useEffect(() => {
    if (billing?.subscription) {
      setContractNo(billing.subscription.contract_no)
      setPlanCode(billing.subscription.plan_code)
      setRateVersionId(billing.subscription.rate_version_id)
      setStartsAt(localDateValue(new Date(billing.subscription.starts_at)))
      setEndsAt(localDateValue(new Date(billing.subscription.ends_at)))
    } else if (rates[0] && !rateVersionId) {
      setRateVersionId(rates[0].id ?? "")
    }
  }, [billing?.subscription, rateVersionId, rates])

  useEffect(() => {
    if (policyQuery.data) {
      setRiskState(policyQuery.data.risk_state)
      setRiskReason(policyQuery.data.reason ?? "")
      setCallsPerMinute(String(policyQuery.data.calls_per_minute))
      setMaxRunningJobs(String(policyQuery.data.max_running_jobs))
      setMaxModelConcurrency(String(policyQuery.data.max_model_concurrency))
      setMaxJobCredits(String(policyQuery.data.max_job_credits))
      setDailyCreditCap(String(policyQuery.data.daily_credit_cap))
      setMonthlyCreditCap(String(policyQuery.data.monthly_credit_cap))
    }
  }, [policyQuery.data])

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["platform-org-billing", orgId] })
    queryClient.invalidateQueries({
      queryKey: ["platform-org-billing-ledger", orgId],
    })
  }

  const contractMutation = useMutation({
    mutationFn: () =>
      PlatformService.upsertOrgSubscription({
        orgId,
        requestBody: {
          contract_no: contractNo.trim(),
          plan_code: planCode.trim(),
          status: "active",
          starts_at: new Date(startsAt).toISOString(),
          ends_at: new Date(endsAt).toISOString(),
          rate_version_id: rateVersionId,
        },
      }),
    onSuccess: () => {
      showSuccessToast("合同已启用")
      setContractOpen(false)
      invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })

  const grantMutation = useMutation({
    mutationFn: () =>
      PlatformService.grantOrgAnswerQuota({
        orgId,
        requestBody: {
          answers: Number(grantAnswers),
          source: "top_up",
          note: grantNote.trim() || null,
        },
      }),
    onSuccess: () => {
      showSuccessToast("答卷额度已发放")
      setGrantAnswers("")
      setGrantNote("")
      setGrantOpen(false)
      invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })

  const policyMutation = useMutation({
    mutationFn: () =>
      PlatformService.updateOrgUsagePolicy({
        orgId,
        requestBody: {
          risk_state: riskState,
          reason: riskState === "normal" ? null : riskReason.trim(),
          calls_per_minute: Number(callsPerMinute),
          max_running_jobs: Number(maxRunningJobs),
          max_model_concurrency: Number(maxModelConcurrency),
          max_job_credits: Number(maxJobCredits),
          daily_credit_cap: Number(dailyCreditCap),
          monthly_credit_cap: Number(monthlyCreditCap),
        },
      }),
    onSuccess: () => {
      showSuccessToast("学校用量状态已更新")
      queryClient.invalidateQueries({
        queryKey: ["platform-org-usage-policy", orgId],
      })
    },
    onError: handleError.bind(showErrorToast),
  })

  if (billingQuery.isPending || !billing) {
    return <Skeleton className="h-72 rounded-[10px]" />
  }

  const subscription = billing.subscription
  const canGrant = canEdit && subscription?.status === "active"

  return (
    <section
      className="overflow-hidden rounded-[10px] border border-border bg-card"
      data-testid="platform-org-billing"
    >
      <div className="flex flex-wrap items-start justify-between gap-4 px-6 py-5">
        <div>
          <div className="flex items-center gap-2">
            <FileCheck2 className="size-4 text-muted-foreground" />
            <h2 className="font-semibold">合同与答卷额度</h2>
            <Tag
              variant={billing.entitlement === "available" ? "mint" : "amber"}
            >
              {ENTITLEMENT_LABELS[billing.entitlement]}
            </Tag>
          </div>
          <p className="mt-3 font-semibold text-3xl tabular-nums">
            {formatNumber(billing.available_answers)}
            <span className="ml-2 font-normal text-muted-foreground text-sm">
              可批改答卷
            </span>
          </p>
        </div>
        {canEdit && (
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => setContractOpen(true)}>
              <CalendarClock />
              {subscription ? "调整合同" : "开通合同"}
            </Button>
            <Button onClick={() => setGrantOpen(true)} disabled={!canGrant}>
              <Plus />
              发放额度
            </Button>
          </div>
        )}
      </div>

      <dl className="grid border-y bg-muted/20 sm:grid-cols-4">
        {[
          ["处理中", formatNumber(billing.reserved_answers)],
          ["已计费答卷", formatNumber(billing.consumed_answers)],
          ["平台模型用量", `${formatNumber(billing.total_tokens)} Token`],
          [
            "合同到期",
            subscription
              ? new Date(subscription.ends_at).toLocaleDateString("zh-CN")
              : "未设置",
          ],
        ].map(([label, value], index) => (
          <div
            key={label}
            className={`px-6 py-4 ${index ? "border-t sm:border-t-0 sm:border-l" : ""}`}
          >
            <dt className="text-muted-foreground text-xs">{label}</dt>
            <dd className="mt-1 font-medium text-sm tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>

      <div className="px-6 py-5">
        <h3 className="font-medium text-sm">平台成本流水</h3>
        {ledgerQuery.data?.data.length ? (
          <div className="mt-3 divide-y">
            {ledgerQuery.data.data.map((entry) => (
              <div
                key={entry.id}
                className="grid grid-cols-[1fr_auto] gap-3 py-2.5 text-sm"
              >
                <div>
                  <span>
                    {ENTRY_LABELS[entry.entry_type] ?? entry.entry_type}
                  </span>
                  {entry.note && (
                    <span className="ml-2 text-muted-foreground">
                      {entry.note}
                    </span>
                  )}
                </div>
                <span className="tabular-nums">
                  {entry.amount_credits > 0 ? "+" : ""}
                  {formatNumber(entry.amount_credits)}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-3 text-muted-foreground text-sm">暂无成本流水</p>
        )}
      </div>

      {canEdit && policyQuery.data && (
        <div className="border-t px-6 py-5">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="grid min-w-44 gap-1.5">
              <Label>用量风控</Label>
              <Select
                value={riskState}
                onValueChange={(value: typeof riskState) => setRiskState(value)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="normal">正常</SelectItem>
                  <SelectItem value="throttled">限速观察</SelectItem>
                  <SelectItem value="blocked">暂停新任务</SelectItem>
                  <SelectItem value="frozen">冻结模型服务</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5 sm:col-span-2">
              <Label htmlFor="risk-reason">原因</Label>
              <Input
                id="risk-reason"
                placeholder="异常用量、合同风险等"
                value={riskReason}
                disabled={riskState === "normal"}
                onChange={(event) => setRiskReason(event.target.value)}
              />
            </div>
            {[
              ["每分钟调用上限", callsPerMinute, setCallsPerMinute],
              ["同时运行任务", maxRunningJobs, setMaxRunningJobs],
              ["学校模型并发", maxModelConcurrency, setMaxModelConcurrency],
              ["单任务成本预算", maxJobCredits, setMaxJobCredits],
              ["每日成本预算", dailyCreditCap, setDailyCreditCap],
              ["每月成本预算", monthlyCreditCap, setMonthlyCreditCap],
            ].map(([label, value, setter]) => (
              <div className="grid gap-1.5" key={label as string}>
                <Label>{label as string}</Label>
                <Input
                  type="number"
                  min={1}
                  value={value as string}
                  onChange={(event) =>
                    (setter as (value: string) => void)(event.target.value)
                  }
                />
              </div>
            ))}
            <div className="flex justify-end sm:col-span-3">
              <LoadingButton
                variant="outline"
                loading={policyMutation.isPending}
                disabled={
                  (riskState !== "normal" && !riskReason.trim()) ||
                  [
                    callsPerMinute,
                    maxRunningJobs,
                    maxModelConcurrency,
                    maxJobCredits,
                    dailyCreditCap,
                    monthlyCreditCap,
                  ].some((value) => Number(value) <= 0)
                }
                onClick={() => policyMutation.mutate()}
              >
                保存用量策略
              </LoadingButton>
            </div>
          </div>
          <p className="mt-2 text-muted-foreground text-xs">
            风控策略在所有 worker
            间统一生效；达到上限后新任务排队，不会绕过成本保护直接调用上游。
          </p>
        </div>
      )}

      <Dialog open={contractOpen} onOpenChange={setContractOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{subscription ? "调整合同" : "开通合同"}</DialogTitle>
            <DialogDescription>
              合同到期后保留历史数据，但停止新上传和新批改任务。
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-1.5 sm:col-span-2">
              <Label htmlFor="contract-no">合同编号</Label>
              <Input
                id="contract-no"
                value={contractNo}
                onChange={(event) => setContractNo(event.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="plan-code">套餐代码</Label>
              <Input
                id="plan-code"
                value={planCode}
                onChange={(event) => setPlanCode(event.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label>计费标准</Label>
              <Select value={rateVersionId} onValueChange={setRateVersionId}>
                <SelectTrigger>
                  <SelectValue placeholder="选择费率版本" />
                </SelectTrigger>
                <SelectContent>
                  {rates.map((rate) => (
                    <SelectItem key={rate.id} value={rate.id ?? ""}>
                      {rate.version}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="contract-start">开始时间</Label>
              <Input
                id="contract-start"
                type="datetime-local"
                value={startsAt}
                onChange={(event) => setStartsAt(event.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="contract-end">结束时间</Label>
              <Input
                id="contract-end"
                type="datetime-local"
                value={endsAt}
                onChange={(event) => setEndsAt(event.target.value)}
              />
            </div>
          </div>
          {!rates.length && (
            <p className="text-amber-700 text-sm">
              请先在系统设置中创建费率版本。
            </p>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setContractOpen(false)}>
              取消
            </Button>
            <LoadingButton
              loading={contractMutation.isPending}
              disabled={
                !contractNo.trim() ||
                !planCode.trim() ||
                !rateVersionId ||
                !startsAt ||
                !endsAt
              }
              onClick={() => contractMutation.mutate()}
            >
              启用合同
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={grantOpen} onOpenChange={setGrantOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>发放答卷额度</DialogTitle>
            <DialogDescription>
              额度与当前合同同时到期。只对成功形成建议结果的有效答卷计费。
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            <div className="grid gap-1.5">
              <Label htmlFor="grant-answers">答卷数量</Label>
              <Input
                id="grant-answers"
                type="number"
                min={1}
                step={100}
                value={grantAnswers}
                onChange={(event) => setGrantAnswers(event.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="grant-note">备注</Label>
              <Input
                id="grant-note"
                placeholder="如：2026 学年首期额度"
                value={grantNote}
                onChange={(event) => setGrantNote(event.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setGrantOpen(false)}>
              取消
            </Button>
            <LoadingButton
              loading={grantMutation.isPending}
              disabled={Number(grantAnswers) <= 0}
              onClick={() => grantMutation.mutate()}
            >
              确认发放
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}
