import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { useState } from "react"

import {
  ModelOfferingsService,
  type PlatformModelOfferingPublic,
  ProviderChannelsService,
  type SchoolModelScope,
} from "@/client"
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
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

const SCOPE_LABELS: Record<SchoolModelScope, string> = {
  vision: "卷面识别",
  reference_answer: "参考答案",
  grading: "建议评分",
}

const SCOPE_ROUTE_PURPOSES: Record<SchoolModelScope, Record<string, string>> = {
  vision: {
    region_detection: "版面分析",
    question_recognition: "题目识别",
    score_structure_recognition: "分值结构识别",
    answer_document_parsing: "答案文档识别",
    rubric_question_recognition: "题目转录",
    answer_recognition: "答题预览",
    answer_extraction: "答题识别",
  },
  reference_answer: {
    answer_preparation: "参考答案解题",
    rubric_generation: "参考答案生成",
    rubric_validation: "参考答案复核",
  },
  grading: {
    subjective_grading: "主观题判分",
  },
}

function modelAllowedForScope(scope: SchoolModelScope, model: string) {
  const normalized = model.toLowerCase()
  return scope === "vision"
    ? normalized.startsWith("gemini-3.6-flash") ||
        normalized.startsWith("gemini-3.5-flash")
    : normalized.startsWith("gpt-5.6-sol") ||
        normalized.startsWith("gpt-5.6-terra") ||
        normalized.startsWith("kimi-")
}

type OfferingForm = {
  code: string
  displayName: string
  description: string
  scope: SchoolModelScope
  canonicalModel: string
  published: boolean
}

const EMPTY_FORM: OfferingForm = {
  code: "",
  displayName: "",
  description: "",
  scope: "vision",
  canonicalModel: "",
  published: false,
}

export function ModelOfferingsSection() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<PlatformModelOfferingPublic | null>(
    null,
  )
  const [form, setForm] = useState(EMPTY_FORM)
  const [rateVersion, setRateVersion] = useState("")
  const [rateInput, setRateInput] = useState("")
  const [rateOutput, setRateOutput] = useState("")
  const [rateImage, setRateImage] = useState("")

  const offerings = useQuery({
    queryKey: ["platform-model-offerings"],
    queryFn: () => ModelOfferingsService.listModelOfferings(),
  })
  const availableTargets = useQuery({
    queryKey: ["platform-model-offering-targets"],
    queryFn: async () => {
      const [channels, routes] = await Promise.all([
        ProviderChannelsService.listChannels(),
        ProviderChannelsService.listRoutePolicies(),
      ])
      const enabledChannels = channels.data.filter(
        (channel) => channel.status === "active",
      )
      const mappings = await Promise.all(
        enabledChannels.map(async (channel) => ({
          channel,
          mappings: await ProviderChannelsService.listModelMappings({
            channelId: channel.id,
          }),
        })),
      )
      const modelCatalog = new Map<
        string,
        {
          channelCount: number
          supportsVision: boolean
          routePurposes: Set<string>
        }
      >()
      for (const { mappings: channelMappings } of mappings) {
        for (const mapping of channelMappings) {
          if (!mapping.enabled) continue
          const current = modelCatalog.get(mapping.canonical_model)
          modelCatalog.set(mapping.canonical_model, {
            channelCount: (current?.channelCount ?? 0) + 1,
            supportsVision:
              Boolean(current?.supportsVision) || mapping.supports_vision,
            routePurposes: current?.routePurposes ?? new Set<string>(),
          })
        }
      }
      for (const route of routes) {
        if (!route.enabled) continue
        modelCatalog
          .get(route.canonical_model)
          ?.routePurposes.add(route.purpose)
      }
      return Array.from(modelCatalog, ([model, metadata]) => ({
        model,
        channelCount: metadata.channelCount,
        supportsVision: metadata.supportsVision,
        routePurposes: Array.from(metadata.routePurposes),
      })).sort((a, b) => a.model.localeCompare(b.model))
    },
  })
  const rates = useQuery({
    queryKey: ["platform-model-offering-rates", editing?.id],
    queryFn: () =>
      ModelOfferingsService.listOfferingRates({ offeringId: editing!.id }),
    enabled: Boolean(editing?.id && open),
  })
  const save = useMutation({
    mutationFn: () => {
      const requestBody = {
        display_name: form.displayName.trim(),
        description: form.description.trim() || null,
        scope: form.scope,
        provider_code: "route",
        canonical_model: form.canonicalModel.trim(),
        published: form.published,
        school_selectable: true,
      }
      return editing
        ? ModelOfferingsService.updateModelOffering({
            offeringId: editing.id,
            requestBody,
          })
        : ModelOfferingsService.createModelOffering({
            requestBody: { ...requestBody, code: form.code.trim() },
          })
    },
    onSuccess: () => {
      showSuccessToast(editing ? "学校方案已保存" : "学校方案已创建")
      setOpen(false)
      queryClient.invalidateQueries({ queryKey: ["platform-model-offerings"] })
    },
    onError: handleError.bind(showErrorToast),
  })
  const createRate = useMutation({
    mutationFn: () =>
      ModelOfferingsService.createOfferingRate({
        offeringId: editing!.id,
        requestBody: {
          version: rateVersion.trim(),
          effective_at: new Date().toISOString(),
          input_credits_per_million: Number(rateInput),
          output_credits_per_million: Number(rateOutput),
          image_credits_per_million: Number(rateImage),
          target_margin_percent: 40,
          minimum_margin_percent: 25,
        },
      }),
    onSuccess: () => {
      showSuccessToast("方案费率已创建，并通过最低毛利校验")
      setRateVersion("")
      setRateInput("")
      setRateOutput("")
      setRateImage("")
      queryClient.invalidateQueries({
        queryKey: ["platform-model-offering-rates", editing?.id],
      })
    },
    onError: handleError.bind(showErrorToast),
  })

  const edit = (item: PlatformModelOfferingPublic) => {
    setEditing(item)
    setForm({
      code: item.code,
      displayName: item.display_name,
      description: item.description ?? "",
      scope: item.scope,
      canonicalModel: item.canonical_model,
      published: item.published,
    })
    setOpen(true)
  }

  const selectedTarget = availableTargets.data?.find(
    (target) => target.model === form.canonicalModel,
  )
  const missingRouteLabels = Object.entries(SCOPE_ROUTE_PURPOSES[form.scope])
    .filter(([purpose]) => !selectedTarget?.routePurposes.includes(purpose))
    .map(([, label]) => label)

  return (
    <section className="rounded-2xl bg-card p-6 shadow-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold">学校可选方案</h3>
          <p className="mt-1 text-muted-foreground text-sm">
            用点凡名称包装真实模型。学校只能看到这里发布的方案。
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setEditing(null)
            setForm(EMPTY_FORM)
            setOpen(true)
          }}
        >
          <Plus />
          添加方案
        </Button>
      </div>

      <div className="mt-5 divide-y border-y">
        {(offerings.data?.data ?? []).map((item) => (
          <button
            type="button"
            key={item.id}
            onClick={() => edit(item)}
            className="grid w-full gap-3 py-3 text-left transition-colors hover:bg-muted/35 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
          >
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-sm">{item.display_name}</span>
                <Tag variant="neutral">{SCOPE_LABELS[item.scope]}</Tag>
                <Tag variant={item.published ? "mint" : "neutral"}>
                  {item.published ? "学校可选" : "未发布"}
                </Tag>
              </div>
              <p className="mt-1 truncate text-muted-foreground text-xs">
                {item.description || "暂无说明"}
              </p>
            </div>
            <div className="flex items-center gap-2 text-muted-foreground text-xs">
              <span>{item.canonical_model}</span>
              <span>· {item.mapped_channel_count} 条可用通道</span>
            </div>
          </button>
        ))}
        {!offerings.isPending && !offerings.data?.count && (
          <div className="py-8 text-center text-muted-foreground text-sm">
            尚未发布学校可选方案
          </div>
        )}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {editing ? "编辑学校方案" : "添加学校方案"}
            </DialogTitle>
            <DialogDescription>
              公开名称给学校看；标准模型由点凡后台在多个通道间自动调度。
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="offering-name">学校看到的名称</Label>
              <Input
                id="offering-name"
                placeholder="如 点凡视觉标准"
                value={form.displayName}
                onChange={(event) =>
                  setForm({ ...form, displayName: event.target.value })
                }
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="offering-code">方案代码</Label>
              <Input
                id="offering-code"
                disabled={Boolean(editing)}
                placeholder="dianfan-vision-standard"
                value={form.code}
                onChange={(event) =>
                  setForm({ ...form, code: event.target.value })
                }
              />
            </div>
            <div className="grid gap-1.5 sm:col-span-2">
              <Label htmlFor="offering-description">学校看到的说明</Label>
              <Input
                id="offering-description"
                placeholder="适合日常试卷识别"
                value={form.description}
                onChange={(event) =>
                  setForm({ ...form, description: event.target.value })
                }
              />
            </div>
            <div className="grid gap-1.5">
              <Label>适用环节</Label>
              <Select
                value={form.scope}
                onValueChange={(scope: SchoolModelScope) =>
                  setForm({
                    ...form,
                    scope,
                    canonicalModel: "",
                  })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(SCOPE_LABELS).map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label>发布状态</Label>
              <Select
                value={form.published ? "published" : "draft"}
                onValueChange={(value) =>
                  setForm({ ...form, published: value === "published" })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="draft">暂不发布</SelectItem>
                  <SelectItem value="published">发布给学校</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5 sm:col-span-2">
              <Label>标准模型</Label>
              <Select
                value={form.canonicalModel || undefined}
                onValueChange={(canonicalModel) =>
                  setForm({ ...form, canonicalModel })
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder="选择通道模型并集中的标准模型" />
                </SelectTrigger>
                <SelectContent>
                  {(availableTargets.data ?? [])
                    .filter((target) =>
                      modelAllowedForScope(form.scope, target.model),
                    )
                    .map((target) => (
                      <SelectItem
                        key={target.model}
                        value={target.model}
                        disabled={
                          (form.scope === "vision" ||
                            form.scope === "reference_answer") &&
                          !target.supportsVision
                        }
                      >
                        {target.model} · {target.channelCount} 条通道 · 路由
                        {
                          Object.keys(SCOPE_ROUTE_PURPOSES[form.scope]).filter(
                            (purpose) => target.routePurposes.includes(purpose),
                          ).length
                        }
                        /{Object.keys(SCOPE_ROUTE_PURPOSES[form.scope]).length}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
              <p className="text-muted-foreground text-xs">
                学校方案不绑定具体中转；实际通道由功能调度自动选择。
              </p>
              {form.published && missingRouteLabels.length > 0 && (
                <p className="text-destructive text-xs">
                  发布前还需配置：{missingRouteLabels.join("、")}。
                </p>
              )}
            </div>
          </div>
          {editing && (
            <div className="border-t pt-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h4 className="font-medium text-sm">计费与毛利保护</h4>
                  <p className="text-muted-foreground text-xs">
                    默认目标毛利 40%，低于 25% 时后端拒绝创建。
                  </p>
                </div>
                {rates.data?.[0] && (
                  <Tag variant={rates.data[0].margin_valid ? "mint" : "red"}>
                    {rates.data[0].version} ·
                    {rates.data[0].margin_valid ? "毛利安全" : "低于保护线"}
                  </Tag>
                )}
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-4">
                <div className="grid gap-1.5">
                  <Label htmlFor="offering-rate-version">版本</Label>
                  <Input
                    id="offering-rate-version"
                    placeholder="2026-08"
                    value={rateVersion}
                    onChange={(event) => setRateVersion(event.target.value)}
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="offering-rate-input">输入积分/百万</Label>
                  <Input
                    id="offering-rate-input"
                    type="number"
                    min={0}
                    value={rateInput}
                    onChange={(event) => setRateInput(event.target.value)}
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="offering-rate-output">输出积分/百万</Label>
                  <Input
                    id="offering-rate-output"
                    type="number"
                    min={0}
                    value={rateOutput}
                    onChange={(event) => setRateOutput(event.target.value)}
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="offering-rate-image">图片积分/百万</Label>
                  <Input
                    id="offering-rate-image"
                    type="number"
                    min={0}
                    value={rateImage}
                    onChange={(event) => setRateImage(event.target.value)}
                  />
                </div>
              </div>
              <div className="mt-3 flex justify-end">
                <LoadingButton
                  variant="outline"
                  size="sm"
                  loading={createRate.isPending}
                  disabled={
                    !rateVersion.trim() ||
                    !rateInput ||
                    !rateOutput ||
                    !rateImage
                  }
                  onClick={() => createRate.mutate()}
                >
                  创建费率版本
                </LoadingButton>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              取消
            </Button>
            <LoadingButton
              loading={save.isPending}
              disabled={
                !form.code.trim() ||
                !form.displayName.trim() ||
                !form.canonicalModel.trim() ||
                (form.published && missingRouteLabels.length > 0)
              }
              onClick={() => save.mutate()}
            >
              保存方案
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}
