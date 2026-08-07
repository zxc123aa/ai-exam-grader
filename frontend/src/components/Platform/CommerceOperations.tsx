import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  BadgeCheck,
  Banknote,
  FileClock,
  PackagePlus,
  ReceiptText,
} from "lucide-react"
import { useState } from "react"

import {
  CommerceService,
  type InvoiceApplicationPublic,
  type RefundRequestPublic,
} from "@/client"
import { EmptyState } from "@/components/Common/EmptyState"
import { PageHead } from "@/components/Common/PageHead"
import { Tag, type TagVariant } from "@/components/Common/Tag"
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

const PANEL_CLASS =
  "overflow-hidden rounded-[10px] border border-border bg-card shadow-[0_1px_2px_rgba(0,0,0,.04)]"

const ORDER_STATUS: Record<string, [string, TagVariant]> = {
  pending_payment: ["待收款", "amber"],
  paid: ["已收款", "sky"],
  fulfilled: ["已开通", "mint"],
  closed: ["已关闭", "neutral"],
  refunding: ["退款中", "amber"],
  refunded: ["已退款", "neutral"],
}

const INVOICE_STATUS: Record<string, [string, TagVariant]> = {
  submitted: ["待处理", "amber"],
  approved: ["待开票", "sky"],
  issued: ["已开票", "mint"],
  rejected: ["已驳回", "red"],
}

const REFUND_STATUS: Record<string, [string, TagVariant]> = {
  requested: ["待审核", "amber"],
  approved: ["已批准", "sky"],
  processing: ["退款中", "amber"],
  succeeded: ["已退款", "mint"],
  rejected: ["已驳回", "red"],
  failed: ["退款失败", "red"],
}

function money(cents: number) {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
  }).format(cents / 100)
}

function count(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value)
}

function dateTime(value: string) {
  return new Date(value).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function StatusTag({
  value,
  labels,
}: {
  value: string
  labels: Record<string, [string, TagVariant]>
}) {
  const [label, variant] = labels[value] ?? [value, "neutral"]
  return <Tag variant={variant}>{label}</Tag>
}

function SectionTitle({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4 border-b px-6 py-5">
      <div>
        <h3 className="font-semibold text-base">{title}</h3>
        <p className="mt-1 text-muted-foreground text-sm">{description}</p>
      </div>
      {action}
    </div>
  )
}

type ProductKind = "plan" | "addon"

function ProductDialog({
  kind,
  open,
  onOpenChange,
}: {
  kind: ProductKind
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const isPlan = kind === "plan"
  const [code, setCode] = useState("")
  const [version, setVersion] = useState("1")
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [price, setPrice] = useState("")
  const [answers, setAnswers] = useState("")
  const [validityDays, setValidityDays] = useState("365")

  const mutation = useMutation({
    mutationFn: async () => {
      if (isPlan) {
        await CommerceService.createPlan({
          requestBody: {
            code: code.trim(),
            version: Number(version),
            display_name: name.trim(),
            description: description.trim() || null,
            annual_price_cents: Math.round(Number(price) * 100),
            included_answers: Number(answers),
            validity_days: Number(validityDays),
            published: false,
          },
        })
        return
      }
      await CommerceService.createAddon({
        requestBody: {
          code: code.trim(),
          display_name: name.trim(),
          description: description.trim() || null,
          price_cents: Math.round(Number(price) * 100),
          answer_quota: Number(answers),
          validity_days: Number(validityDays),
          published: false,
        },
      })
    },
    onSuccess: () => {
      showSuccessToast(isPlan ? "套餐草稿已创建" : "加量包草稿已创建")
      queryClient.invalidateQueries({
        queryKey: [isPlan ? "commerce-plans" : "commerce-addons"],
      })
      onOpenChange(false)
    },
    onError: handleError.bind(showErrorToast),
  })

  const valid =
    code.trim() &&
    name.trim() &&
    price.trim() &&
    answers.trim() &&
    Number(price) >= 0 &&
    Number(answers) >= (isPlan ? 0 : 1) &&
    Number(validityDays) > 0 &&
    (!isPlan || Number(version) > 0)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>
            {isPlan ? "新建年度套餐" : "新建答卷加量包"}
          </DialogTitle>
          <DialogDescription>
            新商品先保存为草稿，确认名称、价格和额度后再单独上架。
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-2 sm:grid-cols-2">
          <div className="grid gap-1.5">
            <Label htmlFor={`${kind}-code`}>商品编码</Label>
            <Input
              id={`${kind}-code`}
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder={isPlan ? "school-standard" : "answers-5000"}
            />
          </div>
          {isPlan && (
            <div className="grid gap-1.5">
              <Label htmlFor="plan-version">版本</Label>
              <Input
                id="plan-version"
                type="number"
                min={1}
                value={version}
                onChange={(event) => setVersion(event.target.value)}
              />
            </div>
          )}
          <div
            className={isPlan ? "grid gap-1.5 sm:col-span-2" : "grid gap-1.5"}
          >
            <Label htmlFor={`${kind}-name`}>对外名称</Label>
            <Input
              id={`${kind}-name`}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={isPlan ? "学校标准版" : "5000 份答卷加量包"}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`${kind}-price`}>售价（元）</Label>
            <Input
              id={`${kind}-price`}
              type="number"
              min={0}
              step="0.01"
              value={price}
              onChange={(event) => setPrice(event.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`${kind}-answers`}>包含答卷数</Label>
            <Input
              id={`${kind}-answers`}
              type="number"
              min={isPlan ? 0 : 1}
              value={answers}
              onChange={(event) => setAnswers(event.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`${kind}-days`}>有效天数</Label>
            <Input
              id={`${kind}-days`}
              type="number"
              min={1}
              value={validityDays}
              onChange={(event) => setValidityDays(event.target.value)}
            />
          </div>
          <div className="grid gap-1.5 sm:col-span-2">
            <Label htmlFor={`${kind}-description`}>购买说明</Label>
            <Input
              id={`${kind}-description`}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="学校购买时看到的简短说明"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <LoadingButton
            loading={mutation.isPending}
            disabled={!valid}
            onClick={() => mutation.mutate()}
          >
            保存草稿
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function CatalogPanel() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [dialog, setDialog] = useState<ProductKind | null>(null)
  const plans = useQuery({
    queryKey: ["commerce-plans"],
    queryFn: () => CommerceService.listPlans(),
  })
  const addons = useQuery({
    queryKey: ["commerce-addons"],
    queryFn: () => CommerceService.listAddons(),
  })

  const publication = useMutation({
    mutationFn: async (item: {
      kind: ProductKind
      id: string
      published: boolean
    }) => {
      if (item.kind === "plan") {
        await CommerceService.updatePlanPublication({
          planId: item.id,
          requestBody: { published: item.published },
        })
        return
      }
      await CommerceService.updateAddonPublication({
        addonId: item.id,
        requestBody: { published: item.published },
      })
    },
    onSuccess: (_data, item) => {
      showSuccessToast(item.published ? "商品已上架" : "商品已下架")
      queryClient.invalidateQueries({ queryKey: ["commerce-plans"] })
      queryClient.invalidateQueries({ queryKey: ["commerce-addons"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <section className={PANEL_CLASS}>
        <SectionTitle
          title="年度套餐"
          description="续费会从当前合同到期日顺延，不覆盖学校剩余服务期。"
          action={
            <Button size="sm" onClick={() => setDialog("plan")}>
              <PackagePlus /> 新建套餐
            </Button>
          }
        />
        <div className="divide-y">
          {(plans.data ?? []).map((plan) => (
            <div
              key={plan.id}
              className="flex items-center justify-between gap-4 px-6 py-4"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{plan.display_name}</span>
                  <Tag variant={plan.published ? "mint" : "neutral"}>
                    {plan.published ? "销售中" : "草稿"}
                  </Tag>
                  <span className="text-muted-foreground text-xs">
                    {plan.code} · v{plan.version}
                  </span>
                </div>
                <p className="mt-1 text-muted-foreground text-sm">
                  {money(plan.annual_price_cents)} / {plan.validity_days} 天 ·
                  含 {count(plan.included_answers)} 份答卷
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                disabled={publication.isPending || !plan.id}
                onClick={() =>
                  plan.id &&
                  publication.mutate({
                    kind: "plan",
                    id: plan.id,
                    published: !plan.published,
                  })
                }
              >
                {plan.published ? "下架" : "上架"}
              </Button>
            </div>
          ))}
          {!plans.isPending && (plans.data ?? []).length === 0 && (
            <div className="p-6 text-muted-foreground text-sm">
              尚未创建年度套餐。
            </div>
          )}
        </div>
      </section>

      <section className={PANEL_CLASS}>
        <SectionTitle
          title="答卷加量包"
          description="仅服务期内的学校可购买，额度和订单保持可追溯。"
          action={
            <Button size="sm" onClick={() => setDialog("addon")}>
              <PackagePlus /> 新建加量包
            </Button>
          }
        />
        <div className="divide-y">
          {(addons.data ?? []).map((addon) => (
            <div
              key={addon.id}
              className="flex items-center justify-between gap-4 px-6 py-4"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{addon.display_name}</span>
                  <Tag variant={addon.published ? "mint" : "neutral"}>
                    {addon.published ? "销售中" : "草稿"}
                  </Tag>
                  <span className="text-muted-foreground text-xs">
                    {addon.code}
                  </span>
                </div>
                <p className="mt-1 text-muted-foreground text-sm">
                  {money(addon.price_cents)} · 增加 {count(addon.answer_quota)}{" "}
                  份答卷 · {addon.validity_days} 天
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                disabled={publication.isPending || !addon.id}
                onClick={() =>
                  addon.id &&
                  publication.mutate({
                    kind: "addon",
                    id: addon.id,
                    published: !addon.published,
                  })
                }
              >
                {addon.published ? "下架" : "上架"}
              </Button>
            </div>
          ))}
          {!addons.isPending && (addons.data ?? []).length === 0 && (
            <div className="p-6 text-muted-foreground text-sm">
              尚未创建答卷加量包。
            </div>
          )}
        </div>
      </section>

      <ProductDialog
        kind="plan"
        open={dialog === "plan"}
        onOpenChange={(open) => setDialog(open ? "plan" : null)}
      />
      <ProductDialog
        kind="addon"
        open={dialog === "addon"}
        onOpenChange={(open) => setDialog(open ? "addon" : null)}
      />
    </div>
  )
}

function OrdersPanel() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [selected, setSelected] = useState<{
    id: string
    orderNo: string
  } | null>(null)
  const [reference, setReference] = useState("")
  const orders = useQuery({
    queryKey: ["commerce-orders"],
    queryFn: () => CommerceService.listOrders(),
  })
  const confirm = useMutation({
    mutationFn: () =>
      CommerceService.confirmBankTransfer({
        orderId: selected?.id ?? "",
        requestBody: { transaction_reference: reference.trim() },
      }),
    onSuccess: () => {
      showSuccessToast("收款已确认，服务和答卷额度已自动开通")
      setSelected(null)
      setReference("")
      queryClient.invalidateQueries({ queryKey: ["commerce-orders"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  if (!orders.isPending && (orders.data ?? []).length === 0) {
    return (
      <EmptyState
        icon={ReceiptText}
        title="还没有订单"
        description="学校提交购买后，订单会在这里等待收款和履约。"
      />
    )
  }

  return (
    <section className={PANEL_CLASS}>
      <SectionTitle
        title="学校订单"
        description="订单按创建时间倒序排列；线下收款确认后系统只履约一次。"
      />
      <div className="p-4 sm:p-6">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>订单 / 学校</TableHead>
              <TableHead>商品</TableHead>
              <TableHead>金额</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>创建时间</TableHead>
              <TableHead className="text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(orders.data ?? []).map((order) => (
              <TableRow key={order.id}>
                <TableCell>
                  <div className="font-medium">{order.order_no}</div>
                  <div className="mt-1 text-muted-foreground text-xs">
                    {order.org_name}
                  </div>
                </TableCell>
                <TableCell className="max-w-72 whitespace-normal">
                  {(order.items ?? [])
                    .map((item) => `${item.display_name} × ${item.quantity}`)
                    .join("、")}
                </TableCell>
                <TableCell className="font-medium tabular-nums">
                  {money(order.amount_cents)}
                </TableCell>
                <TableCell>
                  <StatusTag value={order.status} labels={ORDER_STATUS} />
                </TableCell>
                <TableCell>{dateTime(order.created_at)}</TableCell>
                <TableCell className="text-right">
                  {order.status === "pending_payment" ? (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        setSelected({ id: order.id, orderNo: order.order_no })
                      }
                    >
                      确认收款
                    </Button>
                  ) : (
                    <span className="text-muted-foreground text-xs">
                      无需操作
                    </span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <Dialog
        open={Boolean(selected)}
        onOpenChange={(open) => !open && setSelected(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认线下收款</DialogTitle>
            <DialogDescription>
              订单 {selected?.orderNo}
              。请填写银行流水号或唯一收款凭证号，重复提交不会重复发放额度。
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5 py-2">
            <Label htmlFor="transfer-reference">收款凭证号</Label>
            <Input
              id="transfer-reference"
              value={reference}
              onChange={(event) => setReference(event.target.value)}
              placeholder="例如银行交易流水号"
            />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setSelected(null)}>
              取消
            </Button>
            <LoadingButton
              loading={confirm.isPending}
              disabled={!reference.trim()}
              onClick={() => confirm.mutate()}
            >
              确认收款并开通
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}

function InvoiceReviewDialog({
  item,
  onClose,
}: {
  item: InvoiceApplicationPublic | null
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [invoiceNo, setInvoiceNo] = useState("")
  const [rejectReason, setRejectReason] = useState("")
  const mutation = useMutation({
    mutationFn: (status: "approved" | "issued" | "rejected") =>
      CommerceService.reviewInvoice({
        applicationId: item?.id ?? "",
        requestBody: {
          status,
          invoice_no: status === "issued" ? invoiceNo.trim() : null,
          reject_reason: status === "rejected" ? rejectReason.trim() : null,
        },
      }),
    onSuccess: (_data, status) => {
      showSuccessToast(
        status === "issued"
          ? "发票已登记"
          : status === "approved"
            ? "发票申请已通过"
            : "发票申请已驳回",
      )
      queryClient.invalidateQueries({ queryKey: ["commerce-invoices"] })
      onClose()
    },
    onError: handleError.bind(showErrorToast),
  })
  return (
    <Dialog open={Boolean(item)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>处理发票申请</DialogTitle>
          <DialogDescription>
            {item?.title} · {item ? money(item.amount_cents) : ""} · 接收邮箱{" "}
            {item?.email}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-2">
          <div className="grid gap-1.5">
            <Label htmlFor="invoice-number">发票号码</Label>
            <Input
              id="invoice-number"
              value={invoiceNo}
              onChange={(event) => setInvoiceNo(event.target.value)}
              placeholder="开票完成后填写"
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="invoice-reject">驳回原因</Label>
            <Input
              id="invoice-reject"
              value={rejectReason}
              onChange={(event) => setRejectReason(event.target.value)}
              placeholder="驳回时必填"
            />
          </div>
        </div>
        <DialogFooter className="sm:justify-between">
          <LoadingButton
            variant="ghost"
            className="text-destructive"
            loading={mutation.isPending}
            disabled={!rejectReason.trim()}
            onClick={() => mutation.mutate("rejected")}
          >
            驳回
          </LoadingButton>
          <div className="flex gap-2">
            <LoadingButton
              variant="outline"
              loading={mutation.isPending}
              onClick={() => mutation.mutate("approved")}
            >
              审核通过
            </LoadingButton>
            <LoadingButton
              loading={mutation.isPending}
              disabled={!invoiceNo.trim()}
              onClick={() => mutation.mutate("issued")}
            >
              登记已开票
            </LoadingButton>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function RefundReviewDialog({
  item,
  onClose,
}: {
  item: RefundRequestPublic | null
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [note, setNote] = useState("")
  const mutation = useMutation({
    mutationFn: (
      status: "approved" | "rejected" | "processing" | "succeeded" | "failed",
    ) =>
      CommerceService.reviewRefund({
        refundId: item?.id ?? "",
        requestBody: { status, review_note: note.trim() || null },
      }),
    onSuccess: (_data, status) => {
      showSuccessToast(
        status === "succeeded"
          ? "退款已完成"
          : status === "rejected"
            ? "退款申请已驳回"
            : "退款状态已更新",
      )
      queryClient.invalidateQueries({ queryKey: ["commerce-refunds"] })
      queryClient.invalidateQueries({ queryKey: ["commerce-orders"] })
      onClose()
    },
    onError: handleError.bind(showErrorToast),
  })
  return (
    <Dialog open={Boolean(item)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>处理退款申请</DialogTitle>
          <DialogDescription>
            {item ? money(item.amount_cents) : ""} · {item?.reason}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-1.5 py-2">
          <Label htmlFor="refund-note">处理备注</Label>
          <Input
            id="refund-note"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="记录审核依据或退款流水"
          />
        </div>
        <p className="rounded-[10px] bg-muted px-4 py-3 text-muted-foreground text-sm">
          标记“退款完成”时，系统会核对该订单发放的答卷额度；额度已预留或使用时会阻止自动退款。
        </p>
        <DialogFooter className="sm:justify-between">
          <LoadingButton
            variant="ghost"
            className="text-destructive"
            loading={mutation.isPending}
            onClick={() => mutation.mutate("rejected")}
          >
            驳回
          </LoadingButton>
          <div className="flex gap-2">
            <LoadingButton
              variant="outline"
              loading={mutation.isPending}
              onClick={() => mutation.mutate("approved")}
            >
              批准
            </LoadingButton>
            <LoadingButton
              loading={mutation.isPending}
              onClick={() => mutation.mutate("succeeded")}
            >
              确认退款完成
            </LoadingButton>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function AfterSalesPanel() {
  const [invoice, setInvoice] = useState<InvoiceApplicationPublic | null>(null)
  const [refund, setRefund] = useState<RefundRequestPublic | null>(null)
  const invoices = useQuery({
    queryKey: ["commerce-invoices"],
    queryFn: () => CommerceService.listInvoices(),
  })
  const refunds = useQuery({
    queryKey: ["commerce-refunds"],
    queryFn: () => CommerceService.listRefunds(),
  })
  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <section className={PANEL_CLASS}>
        <SectionTitle
          title="发票申请"
          description="先审核抬头与税号，开票完成后登记发票号码。"
        />
        <div className="divide-y">
          {(invoices.data ?? []).map((item) => (
            <div
              key={item.id}
              className="flex items-center justify-between gap-4 px-6 py-4"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{item.title}</span>
                  <StatusTag value={item.status} labels={INVOICE_STATUS} />
                </div>
                <p className="mt-1 text-muted-foreground text-sm">
                  {money(item.amount_cents)} · {item.tax_number} ·{" "}
                  {dateTime(item.created_at)}
                </p>
              </div>
              {!["issued", "rejected"].includes(item.status) && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setInvoice(item)}
                >
                  处理
                </Button>
              )}
            </div>
          ))}
          {!invoices.isPending && (invoices.data ?? []).length === 0 && (
            <div className="p-6 text-muted-foreground text-sm">
              暂无发票申请。
            </div>
          )}
        </div>
      </section>
      <section className={PANEL_CLASS}>
        <SectionTitle
          title="退款申请"
          description="退款与原订单额度联动，已使用额度不会被静默退回。"
        />
        <div className="divide-y">
          {(refunds.data ?? []).map((item) => (
            <div
              key={item.id}
              className="flex items-center justify-between gap-4 px-6 py-4"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">
                    {money(item.amount_cents)}
                  </span>
                  <StatusTag value={item.status} labels={REFUND_STATUS} />
                </div>
                <p className="mt-1 line-clamp-2 text-muted-foreground text-sm">
                  {item.reason} · {dateTime(item.created_at)}
                </p>
              </div>
              {!["succeeded", "rejected"].includes(item.status) && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setRefund(item)}
                >
                  处理
                </Button>
              )}
            </div>
          ))}
          {!refunds.isPending && (refunds.data ?? []).length === 0 && (
            <div className="p-6 text-muted-foreground text-sm">
              暂无退款申请。
            </div>
          )}
        </div>
      </section>
      <InvoiceReviewDialog item={invoice} onClose={() => setInvoice(null)} />
      <RefundReviewDialog item={refund} onClose={() => setRefund(null)} />
    </div>
  )
}

export function CommerceOperations() {
  const orders = useQuery({
    queryKey: ["commerce-orders"],
    queryFn: () => CommerceService.listOrders(),
  })
  const invoices = useQuery({
    queryKey: ["commerce-invoices"],
    queryFn: () => CommerceService.listInvoices(),
  })
  const refunds = useQuery({
    queryKey: ["commerce-refunds"],
    queryFn: () => CommerceService.listRefunds(),
  })
  const pendingOrders = (orders.data ?? []).filter(
    (item) => item.status === "pending_payment",
  ).length
  const pendingInvoices = (invoices.data ?? []).filter((item) =>
    ["submitted", "approved"].includes(item.status),
  ).length
  const pendingRefunds = (refunds.data ?? []).filter(
    (item) => !["succeeded", "rejected"].includes(item.status),
  ).length

  return (
    <div className="flex flex-col gap-6" data-testid="commerce-operations">
      <PageHead
        title="订单与财务"
        subtitle="管理点凡阅卷的销售商品、学校订单与售后处理"
      />
      <div className="grid gap-px overflow-hidden rounded-[10px] border bg-border sm:grid-cols-3">
        <div className="bg-card px-5 py-4">
          <div className="flex items-center gap-2 text-muted-foreground text-sm">
            <Banknote className="size-4" /> 待确认收款
          </div>
          <div className="mt-2 font-semibold text-2xl tabular-nums">
            {pendingOrders}
          </div>
        </div>
        <div className="bg-card px-5 py-4">
          <div className="flex items-center gap-2 text-muted-foreground text-sm">
            <FileClock className="size-4" /> 待处理发票
          </div>
          <div className="mt-2 font-semibold text-2xl tabular-nums">
            {pendingInvoices}
          </div>
        </div>
        <div className="bg-card px-5 py-4">
          <div className="flex items-center gap-2 text-muted-foreground text-sm">
            <BadgeCheck className="size-4" /> 待处理退款
          </div>
          <div className="mt-2 font-semibold text-2xl tabular-nums">
            {pendingRefunds}
          </div>
        </div>
      </div>
      <Tabs defaultValue="orders" className="gap-5">
        <TabsList>
          <TabsTrigger value="orders">学校订单</TabsTrigger>
          <TabsTrigger value="catalog">销售商品</TabsTrigger>
          <TabsTrigger value="after-sales">发票与退款</TabsTrigger>
        </TabsList>
        <TabsContent value="orders">
          <OrdersPanel />
        </TabsContent>
        <TabsContent value="catalog">
          <CatalogPanel />
        </TabsContent>
        <TabsContent value="after-sales">
          <AfterSalesPanel />
        </TabsContent>
      </Tabs>
    </div>
  )
}
