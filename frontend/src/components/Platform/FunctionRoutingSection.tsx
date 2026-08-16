import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Check,
  CircleDollarSign,
  Gauge,
  GitBranch,
  Settings2,
} from "lucide-react"
import { useMemo, useState } from "react"

import {
  type FunctionModelAssignmentPublic,
  type ModelRoutePolicyPublic,
  type ProviderChannelPublic,
  ProviderChannelsService,
  type ProviderInternalRateVersionPublic,
  type ProviderModelMappingPublic,
} from "@/client"
import { Tag } from "@/components/Common/Tag"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
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
import { cn } from "@/lib/utils"
import { handleError } from "@/utils"

const FUNCTIONS = [
  {
    key: "region_detection",
    label: "版面分析",
    group: "卷面处理",
    vision: true,
    kind: "vision",
  },
  {
    key: "question_recognition",
    label: "题目识别",
    group: "题目与答案",
    vision: true,
    kind: "vision",
  },
  {
    key: "score_structure_recognition",
    label: "分值结构识别",
    group: "题目与答案",
    vision: true,
    kind: "vision",
  },
  {
    key: "answer_preparation",
    label: "参考答案解题",
    group: "题目与答案",
    vision: true,
    kind: "reasoning",
  },
  {
    key: "answer_document_parsing",
    label: "答案文档识别",
    group: "题目与答案",
    vision: true,
    kind: "vision",
  },
  {
    key: "rubric_question_recognition",
    label: "题目转录",
    group: "参考答案",
    vision: true,
    kind: "vision",
  },
  {
    key: "rubric_generation",
    label: "参考答案生成",
    group: "参考答案",
    vision: true,
    kind: "reasoning",
  },
  {
    key: "rubric_validation",
    label: "参考答案复核",
    group: "参考答案",
    vision: true,
    kind: "reasoning",
  },
  {
    key: "answer_recognition",
    label: "答题预览",
    group: "批卷",
    vision: true,
    kind: "vision",
  },
  {
    key: "answer_extraction",
    label: "答题识别",
    group: "批卷",
    vision: true,
    kind: "vision",
  },
  {
    key: "subjective_grading",
    label: "主观题判分",
    group: "批卷",
    vision: false,
    kind: "reasoning",
  },
] as const

type FunctionKind = (typeof FUNCTIONS)[number]["kind"]

const MODEL_PREFERENCES: Record<FunctionKind, string[]> = {
  vision: ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"],
  reasoning: ["gpt-5.6-sol", "gpt-5.6-terra", "kimi-k2.7-code", "kimi-k3"],
}

function modelAllowed(kind: FunctionKind, model: string) {
  const normalized = model.toLowerCase()
  return kind === "vision"
    ? normalized.startsWith("gemini-3.7-flash") ||
        normalized.startsWith("gemini-3.6-flash") ||
        normalized.startsWith("gemini-3.5-flash")
    : normalized.startsWith("gpt-5.6-sol") ||
        normalized.startsWith("gpt-5.6-terra") ||
        normalized.startsWith("kimi-")
}

function sortModels(kind: FunctionKind, models: string[]) {
  const preference = MODEL_PREFERENCES[kind]
  return [...models].sort((a, b) => {
    const aIndex = preference.indexOf(a)
    const bIndex = preference.indexOf(b)
    if (aIndex !== -1 || bIndex !== -1) {
      return (aIndex === -1 ? 999 : aIndex) - (bIndex === -1 ? 999 : bIndex)
    }
    return a.localeCompare(b)
  })
}

type RoutingMode = "balanced" | "cost_first" | "latency_first"

const ROUTING_MODES: Array<{
  value: RoutingMode
  label: string
  description: string
}> = [
  {
    value: "balanced",
    label: "稳定均衡",
    description: "同层按权重分流，兼顾稳定性与供应余量",
  },
  {
    value: "cost_first",
    label: "成本优先",
    description: "同层优先使用内部成本较低的通道",
  },
  {
    value: "latency_first",
    label: "速度优先",
    description: "同层优先使用近期响应更快的通道",
  },
]

const ROUTING_MODE_LABELS: Record<string, string> = Object.fromEntries(
  ROUTING_MODES.map((item) => [item.value, item.label]),
)

type CatalogEntry = {
  channel: ProviderChannelPublic
  mapping: ProviderModelMappingPublic
  rate?: ProviderInternalRateVersionPublic
}

type TargetDraft = {
  selected: boolean
  tier: "1" | "2" | "3"
  weight: string
}

function channelAvailable(entry: CatalogEntry, requiresVision = false) {
  return (
    entry.channel.status === "active" &&
    entry.mapping.enabled &&
    (!requiresVision || entry.mapping.supports_vision) &&
    entry.mapping.usage_metering_verified
  )
}

function formatCost(rate?: ProviderInternalRateVersionPublic) {
  if (!rate) return "未配置内部成本"
  return `成本 入 ¥${rate.input_rmb_per_million} / 出 ¥${rate.output_rmb_per_million}`
}

export function FunctionRoutingSection() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [editingPurpose, setEditingPurpose] = useState<string | null>(null)
  const [canonicalModel, setCanonicalModel] = useState("")
  const [maxAttempts, setMaxAttempts] = useState("3")
  const [routingMode, setRoutingMode] = useState<RoutingMode>("balanced")
  const [makeDefault, setMakeDefault] = useState(false)
  const [targetDrafts, setTargetDrafts] = useState<Record<string, TargetDraft>>(
    {},
  )

  const catalogQuery = useQuery({
    queryKey: ["platform-routing-catalog"],
    queryFn: async () => {
      const channels = await ProviderChannelsService.listChannels()
      const rows = await Promise.all(
        channels.data.map(async (channel) => {
          const [mappings, rates] = await Promise.all([
            ProviderChannelsService.listModelMappings({
              channelId: channel.id,
            }),
            ProviderChannelsService.listInternalRates({
              channelId: channel.id,
            }),
          ])
          return { channel, mappings, rates }
        }),
      )
      return rows.flatMap(({ channel, mappings, rates }) =>
        mappings.map((mapping) => ({
          channel,
          mapping,
          rate: rates.find(
            (rate) =>
              rate.canonical_model === mapping.canonical_model &&
              new Date(rate.effective_at).getTime() <= Date.now(),
          ),
        })),
      )
    },
  })
  const routesQuery = useQuery({
    queryKey: ["platform-function-routes"],
    queryFn: () => ProviderChannelsService.listRoutePolicies(),
  })
  const defaultsQuery = useQuery({
    queryKey: ["platform-function-route-defaults"],
    queryFn: () => ProviderChannelsService.listFunctionModelDefaults(),
  })

  const entries = catalogQuery.data ?? []
  const routesByPurpose = useMemo(() => {
    const result = new Map<string, ModelRoutePolicyPublic[]>()
    for (const route of routesQuery.data ?? []) {
      if (!route.enabled) continue
      result.set(route.purpose, [...(result.get(route.purpose) ?? []), route])
    }
    for (const routes of result.values()) {
      routes.sort((a, b) => a.canonical_model.localeCompare(b.canonical_model))
    }
    return result
  }, [routesQuery.data])
  const defaults = useMemo(
    () =>
      new Map<string, FunctionModelAssignmentPublic>(
        (defaultsQuery.data ?? []).map((item) => [item.purpose, item]),
      ),
    [defaultsQuery.data],
  )
  const canonicalModels = useMemo(
    () =>
      Array.from(
        new Set(
          entries
            .filter((entry) => entry.mapping.supports_structured_output)
            .map((entry) => entry.mapping.canonical_model),
        ),
      ).sort(),
    [entries],
  )
  const selectedEntries = entries.filter(
    (entry) => entry.mapping.canonical_model === canonicalModel,
  )

  const loadModel = (purpose: string, model: string) => {
    const current = (routesByPurpose.get(purpose) ?? []).find(
      (route) => route.canonical_model === model,
    )
    const requiresVision =
      FUNCTIONS.find((item) => item.key === purpose)?.vision ?? false
    const targets = new Map(
      current?.targets.map((target) => [target.mapping_id, target]) ?? [],
    )
    const tierByPriority = new Map(
      Array.from(
        new Set(
          current?.targets
            .filter((target) => target.enabled)
            .map((target) => target.priority) ?? [],
        ),
      )
        .sort((a, b) => a - b)
        .map((priority, index) => [priority, Math.min(3, index + 1)]),
    )
    setCanonicalModel(model)
    setMaxAttempts(String(current?.max_attempts ?? 3))
    setRoutingMode((current?.routing_mode as RoutingMode) ?? "balanced")
    setMakeDefault(
      !defaults.get(purpose) ||
        defaults.get(purpose)?.default_canonical_model === model,
    )
    setTargetDrafts(
      Object.fromEntries(
        entries
          .filter((entry) => entry.mapping.canonical_model === model)
          .map((entry) => {
            const target = targets.get(entry.mapping.id)
            return [
              entry.mapping.id,
              {
                selected: current
                  ? Boolean(
                      target?.enabled &&
                        channelAvailable(entry, requiresVision),
                    )
                  : channelAvailable(entry, requiresVision),
                tier: String(
                  target ? (tierByPriority.get(target.priority) ?? 1) : 1,
                ) as TargetDraft["tier"],
                weight: String(target?.weight ?? 100),
              },
            ]
          }),
      ),
    )
  }

  const openEditor = (purpose: string) => {
    const definition = FUNCTIONS.find((item) => item.key === purpose)
    if (!definition) return
    const availableRoutes = (routesByPurpose.get(purpose) ?? []).filter(
      (route) => modelAllowed(definition.kind, route.canonical_model),
    )
    const allowedModels = sortModels(
      definition.kind,
      canonicalModels.filter((model) => modelAllowed(definition.kind, model)),
    )
    const assignedDefault = defaults.get(purpose)?.default_canonical_model
    const model =
      (assignedDefault && modelAllowed(definition.kind, assignedDefault)
        ? assignedDefault
        : undefined) ??
      availableRoutes[0]?.canonical_model ??
      allowedModels[0] ??
      ""
    setEditingPurpose(purpose)
    loadModel(purpose, model)
  }

  const publishMutation = useMutation({
    mutationFn: async () => {
      const purpose = editingPurpose!
      const targets = selectedEntries
        .filter((entry) => targetDrafts[entry.mapping.id]?.selected)
        .map((entry) => ({
          mapping_id: entry.mapping.id,
          priority: Number(targetDrafts[entry.mapping.id].tier),
          weight: Number(targetDrafts[entry.mapping.id].weight),
          enabled: true,
        }))
      const policy = await ProviderChannelsService.upsertRoutePolicy({
        purpose,
        requestBody: {
          canonical_model: canonicalModel,
          enabled: true,
          max_attempts: Number(maxAttempts),
          routing_mode: routingMode,
          targets,
        },
      })
      const versions = await ProviderChannelsService.listRouteVersions({
        purpose,
        canonicalModel,
      })
      const draft = versions.find(
        (version) =>
          version.policy_id === policy.id && version.status === "draft",
      )
      if (!draft) throw new Error("未找到待发布的路由版本")
      await ProviderChannelsService.publishRouteVersion({
        purpose,
        versionId: draft.id,
      })
      if (makeDefault) {
        await ProviderChannelsService.updateFunctionModelDefault({
          purpose,
          requestBody: { canonical_model: canonicalModel },
        })
      }
    },
    onSuccess: () => {
      showSuccessToast("模型路由已发布，新任务立即使用")
      setEditingPurpose(null)
      queryClient.invalidateQueries({ queryKey: ["platform-function-routes"] })
      queryClient.invalidateQueries({
        queryKey: ["platform-function-route-defaults"],
      })
    },
    onError: handleError.bind(showErrorToast),
  })

  const selectedCount = selectedEntries.filter(
    (entry) => targetDrafts[entry.mapping.id]?.selected,
  ).length
  const missingRateCount = selectedEntries.filter(
    (entry) => targetDrafts[entry.mapping.id]?.selected && !entry.rate,
  ).length
  const editingFunction = FUNCTIONS.find((item) => item.key === editingPurpose)
  const editingCanonicalModels = editingFunction
    ? sortModels(
        editingFunction.kind,
        canonicalModels.filter((model) =>
          modelAllowed(editingFunction.kind, model),
        ),
      )
    : []
  const editingRoutes = editingPurpose
    ? (routesByPurpose.get(editingPurpose) ?? []).filter(
        (route) =>
          !editingFunction ||
          modelAllowed(editingFunction.kind, route.canonical_model),
      )
    : []
  const currentDefault = editingPurpose
    ? defaults.get(editingPurpose)?.default_canonical_model
    : undefined

  return (
    <>
      <section className="rounded-[10px] border bg-card shadow-card">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b px-5 py-4">
          <div>
            <h2 className="font-semibold">业务功能路由</h2>
            <p className="mt-1 text-muted-foreground text-sm">
              视觉识别使用 Gemini；解题与判分使用 GPT-5.6 Sol，并可配置 Terra 或
              Kimi 备用。
            </p>
          </div>
          <div className="flex items-center gap-2 text-muted-foreground text-xs">
            <span>
              {routesByPurpose.size}/{FUNCTIONS.length} 已配置
            </span>
            <span>·</span>
            <span>{canonicalModels.length} 个标准模型</span>
          </div>
        </div>

        <div className="divide-y">
          {FUNCTIONS.map((item) => {
            const routes = (routesByPurpose.get(item.key) ?? []).filter(
              (route) => modelAllowed(item.kind, route.canonical_model),
            )
            const defaultModel = defaults.get(item.key)?.default_canonical_model
            const displayedRoutes = [...routes].sort((a, b) => {
              if (a.canonical_model === defaultModel) return -1
              if (b.canonical_model === defaultModel) return 1
              return a.canonical_model.localeCompare(b.canonical_model)
            })
            const routeMappingIds = new Set(
              routes.flatMap((route) =>
                route.targets
                  .filter((target) => target.enabled)
                  .map((target) => target.mapping_id),
              ),
            )
            const channels = new Set(
              entries
                .filter(
                  (entry) =>
                    routeMappingIds.has(entry.mapping.id) &&
                    channelAvailable(entry, item.vision),
                )
                .map((entry) => entry.channel.id),
            ).size
            return (
              <div
                key={item.key}
                data-testid={`function-route-${item.key}`}
                className="grid gap-3 px-5 py-3.5 lg:grid-cols-[minmax(10rem,.7fr)_minmax(0,1.8fr)_auto] lg:items-center"
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">{item.label}</span>
                  <Tag variant="neutral">{item.group}</Tag>
                  <Tag variant="neutral">
                    {item.kind === "vision" ? "视觉识别" : "推理解题"}
                  </Tag>
                </div>
                {routes.length ? (
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {displayedRoutes.slice(0, 3).map((route) => (
                        <span
                          key={route.id}
                          className="inline-flex items-center gap-1 rounded-md border bg-muted/20 px-2 py-1 font-mono text-xs"
                        >
                          {route.canonical_model}
                          {route.canonical_model === defaultModel && (
                            <span className="font-sans text-primary">默认</span>
                          )}
                        </span>
                      ))}
                      {routes.length > 3 && (
                        <span className="text-muted-foreground text-xs">
                          +{routes.length - 3}
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-muted-foreground text-xs">
                      {routes.length} 个可用模型 · {channels} 条中转通道
                    </p>
                  </div>
                ) : (
                  <p className="text-muted-foreground text-sm">
                    尚未发布可用模型
                  </p>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => openEditor(item.key)}
                >
                  <Settings2 />
                  {routes.length ? "管理" : "配置"}
                </Button>
              </div>
            )
          })}
        </div>
      </section>

      <Dialog
        open={Boolean(editingPurpose)}
        onOpenChange={(open) => !open && setEditingPurpose(null)}
      >
        <DialogContent className="max-h-[94vh] overflow-y-auto sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle>{editingFunction?.label ?? "功能调度"}</DialogTitle>
            <DialogDescription>
              {editingFunction?.kind === "vision"
                ? "纯视觉任务只使用 Gemini 3.6/3.5 Flash。"
                : "推理解题优先使用 GPT-5.6 Sol，可配置 Terra 或 Kimi 备用。"}
              每个模型独立配置主备通道，学校选择后仍走对应路由。
            </DialogDescription>
          </DialogHeader>

          <div className="border-y">
            <div className="flex flex-wrap items-center gap-2 border-b bg-muted/20 px-3 py-2">
              <span className="mr-1 text-muted-foreground text-xs">
                已发布模型
              </span>
              {editingRoutes.map((route) => (
                <button
                  type="button"
                  key={route.id}
                  onClick={() =>
                    loadModel(editingPurpose!, route.canonical_model)
                  }
                  className={cn(
                    "inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 font-mono text-xs transition-colors",
                    route.canonical_model === canonicalModel
                      ? "border-primary bg-primary/5 text-primary"
                      : "bg-background hover:bg-muted/50",
                  )}
                >
                  {route.canonical_model}
                  {route.canonical_model === currentDefault && (
                    <Check className="size-3.5" />
                  )}
                </button>
              ))}
              {!editingRoutes.length && (
                <span className="text-muted-foreground text-xs">暂无</span>
              )}
            </div>

            <div className="grid gap-4 px-3 py-3 sm:grid-cols-[minmax(0,1fr)_11rem_11rem]">
              <div className="grid gap-1.5">
                <Label>选择或添加标准模型</Label>
                <Select
                  value={canonicalModel}
                  onValueChange={(model) => loadModel(editingPurpose!, model)}
                >
                  <SelectTrigger data-testid="routing-model-select">
                    <SelectValue placeholder="选择通道模型并集中的标准模型" />
                  </SelectTrigger>
                  <SelectContent>
                    {editingCanonicalModels.map((model) => {
                      const count = entries.filter(
                        (entry) =>
                          entry.mapping.canonical_model === model &&
                          channelAvailable(entry, editingFunction?.vision),
                      ).length
                      const configured = editingRoutes.some(
                        (route) => route.canonical_model === model,
                      )
                      return (
                        <SelectItem key={model} value={model}>
                          {model} · {count} 条通道
                          {configured ? " · 已发布" : ""}
                        </SelectItem>
                      )
                    })}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-1.5">
                <Label>调度策略</Label>
                <Select
                  value={routingMode}
                  onValueChange={(value: RoutingMode) => setRoutingMode(value)}
                >
                  <SelectTrigger data-testid="routing-mode-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ROUTING_MODES.map((mode) => (
                      <SelectItem key={mode.value} value={mode.value}>
                        {mode.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="routing-attempts">失败后最多尝试</Label>
                <Input
                  id="routing-attempts"
                  type="number"
                  min={1}
                  max={10}
                  value={maxAttempts}
                  onChange={(event) => setMaxAttempts(event.target.value)}
                />
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border bg-muted/15 px-3 py-2 text-xs">
            <div className="flex items-center gap-2">
              {routingMode === "cost_first" ? (
                <CircleDollarSign className="size-4 text-muted-foreground" />
              ) : routingMode === "latency_first" ? (
                <Gauge className="size-4 text-muted-foreground" />
              ) : (
                <GitBranch className="size-4 text-muted-foreground" />
              )}
              <span>{ROUTING_MODE_LABELS[routingMode]}</span>
              <span className="text-muted-foreground">
                {
                  ROUTING_MODES.find((item) => item.value === routingMode)
                    ?.description
                }
              </span>
            </div>
            <span className="text-muted-foreground">
              {selectedCount} 条已选通道
            </span>
          </div>

          <div className="border-y">
            <div className="grid grid-cols-[minmax(0,1fr)_7rem_6rem] gap-3 border-b bg-muted/20 px-3 py-2 text-muted-foreground text-xs">
              <span>提供该模型的通道</span>
              <span>调度层级</span>
              <span>同层权重</span>
            </div>
            {selectedEntries.map((entry) => {
              const draft = targetDrafts[entry.mapping.id] ?? {
                selected: false,
                tier: "1" as const,
                weight: "100",
              }
              const available = channelAvailable(entry, editingFunction?.vision)
              const unavailableReason =
                entry.channel.status !== "active"
                  ? "通道未启用"
                  : editingFunction?.vision && !entry.mapping.supports_vision
                    ? "不支持图片输入"
                    : !entry.mapping.usage_metering_verified
                      ? "需先完成模型检测"
                      : "映射已停用"
              return (
                <div
                  key={entry.mapping.id}
                  className="grid grid-cols-[minmax(0,1fr)_7rem_6rem] items-center gap-3 px-3 py-3"
                >
                  <label
                    htmlFor={`route-target-${entry.mapping.id}`}
                    className="flex min-w-0 items-start gap-2.5"
                  >
                    <Checkbox
                      id={`route-target-${entry.mapping.id}`}
                      checked={draft.selected}
                      disabled={!available}
                      onCheckedChange={(checked) =>
                        setTargetDrafts((current) => ({
                          ...current,
                          [entry.mapping.id]: {
                            ...draft,
                            selected: Boolean(checked),
                          },
                        }))
                      }
                    />
                    <span className="min-w-0">
                      <span className="block truncate font-medium text-sm">
                        {entry.channel.display_name}
                      </span>
                      <span className="block truncate text-muted-foreground text-xs">
                        上游 {entry.mapping.upstream_model} · 并发{" "}
                        {entry.channel.max_concurrency}
                        {available
                          ? ` · ${formatCost(entry.rate)}`
                          : ` · ${unavailableReason}`}
                      </span>
                    </span>
                  </label>
                  <Select
                    value={draft.tier}
                    disabled={!draft.selected}
                    onValueChange={(tier: TargetDraft["tier"]) =>
                      setTargetDrafts((current) => ({
                        ...current,
                        [entry.mapping.id]: { ...draft, tier },
                      }))
                    }
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="1">主用</SelectItem>
                      <SelectItem value="2">备用一</SelectItem>
                      <SelectItem value="3">备用二</SelectItem>
                    </SelectContent>
                  </Select>
                  <Input
                    className="h-8"
                    type="number"
                    min={1}
                    max={10000}
                    disabled={!draft.selected}
                    value={draft.weight}
                    onChange={(event) =>
                      setTargetDrafts((current) => ({
                        ...current,
                        [entry.mapping.id]: {
                          ...draft,
                          weight: event.target.value,
                        },
                      }))
                    }
                  />
                </div>
              )
            })}
            {!selectedEntries.length && (
              <div className="py-8 text-center text-muted-foreground text-sm">
                该标准模型还没有通道映射，请先到中转通道中添加。
              </div>
            )}
          </div>

          {routingMode === "cost_first" && missingRateCount > 0 && (
            <p className="text-destructive text-xs">
              {missingRateCount}{" "}
              条已选通道尚未配置内部成本，不能发布成本优先策略。
            </p>
          )}

          <label
            htmlFor="routing-default-model"
            className="flex items-start gap-2 rounded-md border px-3 py-2.5"
          >
            <Checkbox
              id="routing-default-model"
              checked={makeDefault}
              onCheckedChange={(checked) => setMakeDefault(Boolean(checked))}
            />
            <span>
              <span className="block font-medium text-sm">
                设为平台默认模型
              </span>
              <span className="block text-muted-foreground text-xs">
                未单独选择方案的学校使用此模型；其他已发布模型仍保持可用。
              </span>
            </span>
          </label>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditingPurpose(null)}>
              取消
            </Button>
            <LoadingButton
              data-testid="routing-publish"
              loading={publishMutation.isPending}
              disabled={
                !canonicalModel ||
                selectedCount === 0 ||
                Number(maxAttempts) < 1 ||
                Number(maxAttempts) > 10 ||
                (routingMode === "cost_first" && missingRateCount > 0)
              }
              onClick={() => publishMutation.mutate()}
            >
              保存并发布此模型
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
