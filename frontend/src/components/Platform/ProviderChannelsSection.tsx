import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import {
  Download,
  KeyRound,
  Plus,
  ReceiptText,
  RefreshCw,
  RotateCw,
  Settings2,
} from "lucide-react"
import { useEffect, useState } from "react"

import {
  type ProviderChannelKind,
  type ProviderChannelPublic,
  type ProviderChannelStatus,
  ProviderChannelsService,
  type ProviderChannelTestResult,
  type ProviderModelMappingPublic,
  type ProviderProtocol,
  type ProviderStatus,
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
import { handleError } from "@/utils"

const KIND_LABELS: Record<ProviderChannelKind, string> = {
  official_api: "官方接口",
  authorized_relay: "授权中转",
  new_api: "New API",
  sub2api: "Sub2API",
  cli_proxy_api: "CPA 兼容服务",
  custom: "自定义中转",
}

const HEALTH_LABELS: Record<string, string> = {
  unknown: "未检测",
  healthy: "正常",
  degraded: "波动",
  open: "已熔断",
  disabled: "已停用",
}

const CHANNEL_STATUS_LABELS: Record<ProviderChannelStatus, string> = {
  draft: "草稿",
  active: "运行中",
  draining: "排空中",
  disabled: "已停用",
}

type ChannelForm = {
  code: string
  displayName: string
  kind: ProviderChannelKind
  protocol: ProviderProtocol
  baseUrl: string
  apiKey: string
  maxConcurrency: string
  timeoutSeconds: string
  status: ProviderChannelStatus
  riskAcknowledged: boolean
}

const EMPTY_FORM: ChannelForm = {
  code: "",
  displayName: "",
  kind: "authorized_relay",
  protocol: "openai_chat",
  baseUrl: "",
  apiKey: "",
  maxConcurrency: "8",
  timeoutSeconds: "180",
  status: "draft",
  riskAcknowledged: false,
}

function formFromChannel(channel: ProviderChannelPublic): ChannelForm {
  return {
    code: channel.code,
    displayName: channel.display_name,
    kind: channel.kind,
    protocol: channel.protocol,
    baseUrl: channel.base_url,
    apiKey: "",
    maxConcurrency: String(channel.max_concurrency),
    timeoutSeconds: String(channel.timeout_seconds),
    status: channel.status,
    riskAcknowledged: channel.risk_acknowledged,
  }
}

export function ProviderChannelsSection({
  legacyProviders,
}: {
  legacyProviders: ProviderStatus[]
}) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [editing, setEditing] = useState<ProviderChannelPublic | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [form, setForm] = useState<ChannelForm>(EMPTY_FORM)
  const [canonicalModel, setCanonicalModel] = useState("")
  const [upstreamModel, setUpstreamModel] = useState("")
  const [supportsVision, setSupportsVision] = useState(true)
  const [supportsStructuredOutput, setSupportsStructuredOutput] = useState(true)
  const [mappingDrafts, setMappingDrafts] = useState<Record<string, string>>({})
  const [discoveredModels, setDiscoveredModels] = useState<string[] | null>(
    null,
  )
  const [testingMappingId, setTestingMappingId] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<
    Record<string, ProviderChannelTestResult>
  >({})
  const [reconciliationCsv, setReconciliationCsv] = useState("")
  const [billingAccessToken, setBillingAccessToken] = useState("")
  const [billingUserId, setBillingUserId] = useState("")

  const channelsQuery = useQuery({
    queryKey: ["platform-provider-channels"],
    queryFn: () => ProviderChannelsService.listChannels(),
  })
  const channelMappings = useQueries({
    queries: (channelsQuery.data?.data ?? []).map((channel) => ({
      queryKey: ["platform-provider-channel-models", channel.id],
      queryFn: () =>
        ProviderChannelsService.listModelMappings({ channelId: channel.id }),
    })),
  })
  const mappingsQuery = useQuery({
    queryKey: ["platform-provider-channel-models", editing?.id],
    queryFn: () =>
      ProviderChannelsService.listModelMappings({ channelId: editing!.id }),
    enabled: Boolean(editing?.id && dialogOpen),
  })
  const reconciliationsQuery = useQuery({
    queryKey: ["platform-provider-reconciliations", editing?.id],
    queryFn: () =>
      ProviderChannelsService.listReconciliations({
        channelId: editing!.id,
      }),
    enabled: Boolean(editing?.id && dialogOpen),
  })

  useEffect(() => {
    if (!dialogOpen) {
      setCanonicalModel("")
      setUpstreamModel("")
      setSupportsVision(true)
      setSupportsStructuredOutput(true)
      setDiscoveredModels(null)
      setTestingMappingId(null)
      setTestResults({})
      setReconciliationCsv("")
      setBillingAccessToken("")
      setBillingUserId("")
    }
  }, [dialogOpen])

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["platform-provider-channels"] })
    if (editing) {
      queryClient.invalidateQueries({
        queryKey: ["platform-provider-channel-models", editing.id],
      })
    }
    queryClient.invalidateQueries({ queryKey: ["platform-system-config"] })
  }

  const saveMutation = useMutation({
    mutationFn: async () => {
      const common = {
        display_name: form.displayName.trim(),
        kind: form.kind,
        protocol: form.protocol,
        base_url: form.baseUrl.trim(),
        status: form.status,
        risk_acknowledged: form.riskAcknowledged,
        max_concurrency: Number(form.maxConcurrency),
        timeout_seconds: Number(form.timeoutSeconds),
      }
      if (!editing) {
        return ProviderChannelsService.createChannel({
          requestBody: {
            ...common,
            code: form.code.trim(),
            api_key: form.apiKey.trim() || null,
          },
        })
      }
      if (form.apiKey.trim()) {
        await ProviderChannelsService.rotateCredential({
          channelId: editing.id,
          requestBody: { api_key: form.apiKey.trim() },
        })
      }
      return ProviderChannelsService.updateChannel({
        channelId: editing.id,
        requestBody: common,
      })
    },
    onSuccess: () => {
      showSuccessToast(editing ? "中转设置已保存" : "中转已添加")
      setDialogOpen(false)
      invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })

  const mappingMutation = useMutation({
    mutationFn: () =>
      ProviderChannelsService.createModelMapping({
        channelId: editing!.id,
        requestBody: {
          canonical_model: canonicalModel.trim(),
          upstream_model: upstreamModel.trim(),
          supports_vision: supportsVision,
          supports_structured_output: supportsStructuredOutput,
        },
      }),
    onSuccess: () => {
      showSuccessToast("模型映射已添加；完成检测后可在功能调度中使用")
      setCanonicalModel("")
      setUpstreamModel("")
      setSupportsVision(true)
      setSupportsStructuredOutput(true)
      invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })

  const mappingUpdateMutation = useMutation({
    mutationFn: async ({
      mapping,
      patch,
    }: {
      mapping: ProviderModelMappingPublic
      patch: {
        upstream_model?: string
        supports_vision?: boolean
        supports_structured_output?: boolean
        enabled?: boolean
      }
    }) =>
      ProviderChannelsService.updateModelMapping({
        channelId: mapping.channel_id,
        mappingId: mapping.id,
        requestBody: patch,
      }),
    onSuccess: (mapping) => {
      showSuccessToast("模型设置已保存")
      setMappingDrafts((current) => ({
        ...current,
        [mapping.id]: mapping.upstream_model,
      }))
      invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })

  const importMutation = useMutation({
    mutationFn: () => ProviderChannelsService.importEnvironmentChannels(),
    onSuccess: (result) => {
      showSuccessToast(`已纳管 ${result.count} 个调用通道`)
      queryClient.invalidateQueries({
        queryKey: ["platform-provider-channels"],
      })
      queryClient.invalidateQueries({ queryKey: ["platform-model-offerings"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  const testMutation = useMutation({
    mutationFn: ({ model }: { mappingId: string; model: string }) =>
      ProviderChannelsService.testChannel({
        channelId: editing!.id,
        requestBody: { canonical_model: model },
      }),
    onMutate: ({ mappingId }) => {
      setTestingMappingId(mappingId)
      setTestResults((current) => {
        const next = { ...current }
        delete next[mappingId]
        return next
      })
    },
    onSuccess: (result, { mappingId }) => {
      setTestResults((current) => ({ ...current, [mappingId]: result }))
      if (result.ok) {
        showSuccessToast(`连接正常，耗时 ${result.latency_ms} ms`)
      } else {
        showErrorToast(result.error || "连接检测未通过")
      }
      invalidate()
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => setTestingMappingId(null),
  })

  const discoverMutation = useMutation({
    mutationFn: () =>
      ProviderChannelsService.discoverUpstreamModels({
        channelId: editing!.id,
      }),
    onSuccess: (result) => {
      setDiscoveredModels(result.models)
      showSuccessToast(`读取到 ${result.count} 个上游模型`)
    },
    onError: handleError.bind(showErrorToast),
  })

  const reconciliationMutation = useMutation({
    mutationFn: () => {
      const rows = reconciliationCsv
        .trim()
        .split(/\r?\n/)
        .map((line) => line.split(",").map((value) => value.trim()))
        .filter((columns) => columns.length >= 4 && columns[0])
        .map(([upstream_request_id, input, output, cost]) => ({
          upstream_request_id,
          input_tokens: Number(input),
          output_tokens: Number(output),
          cost_rmb: Number(cost),
        }))
      return ProviderChannelsService.importReconciliation({
        channelId: editing!.id,
        requestBody: {
          source: "csv",
          period_start: new Date(Date.now() - 7 * 86400_000).toISOString(),
          period_end: new Date().toISOString(),
          rows,
        },
      })
    },
    onSuccess: (batch) => {
      showSuccessToast(
        `对账完成：匹配 ${batch.matched_count} 条，异常 ${batch.mismatch_count} 条`,
      )
      setReconciliationCsv("")
      queryClient.invalidateQueries({
        queryKey: ["platform-provider-reconciliations", editing?.id],
      })
      queryClient.invalidateQueries({
        queryKey: ["platform-model-usage-overview"],
      })
      queryClient.invalidateQueries({
        queryKey: ["platform-model-usage-events"],
      })
    },
    onError: handleError.bind(showErrorToast),
  })

  const newApiSyncMutation = useMutation({
    mutationFn: () =>
      ProviderChannelsService.syncNewApiReconciliation({
        channelId: editing!.id,
      }),
    onSuccess: (result) => {
      showSuccessToast(result.message)
      queryClient.invalidateQueries({
        queryKey: ["platform-provider-reconciliations", editing?.id],
      })
      queryClient.invalidateQueries({
        queryKey: ["platform-model-usage-overview"],
      })
      queryClient.invalidateQueries({
        queryKey: ["platform-model-usage-events"],
      })
    },
    onError: handleError.bind(showErrorToast),
  })

  const billingCredentialMutation = useMutation({
    mutationFn: () =>
      ProviderChannelsService.rotateBillingCredential({
        channelId: editing!.id,
        requestBody: {
          access_token: billingAccessToken.trim(),
          user_id:
            editing?.kind === "new_api" ? Number(billingUserId) : undefined,
        },
      }),
    onSuccess: (channel) => {
      setEditing(channel)
      setBillingAccessToken("")
      setBillingUserId(String(channel.billing_user_id ?? ""))
      showSuccessToast("账单凭据已保存")
      queryClient.invalidateQueries({
        queryKey: ["platform-provider-channels"],
      })
    },
    onError: handleError.bind(showErrorToast),
  })

  const openCreate = () => {
    setEditing(null)
    setForm(EMPTY_FORM)
    setDialogOpen(true)
  }
  const openEdit = (channel: ProviderChannelPublic) => {
    setEditing(channel)
    setForm(formFromChannel(channel))
    setDiscoveredModels(null)
    setTestResults({})
    setBillingAccessToken("")
    setBillingUserId(String(channel.billing_user_id ?? ""))
    setDialogOpen(true)
  }

  const riskKind = ["sub2api", "cli_proxy_api", "custom"].includes(form.kind)
  const canSave =
    form.code.trim() &&
    form.displayName.trim() &&
    form.baseUrl.trim() &&
    Number(form.maxConcurrency) > 0 &&
    Number(form.timeoutSeconds) >= 5 &&
    (form.status !== "active" ||
      Boolean(editing?.credential_configured || form.apiKey.trim()))

  const managedCodes = new Set(
    (channelsQuery.data?.data ?? []).map((channel) => channel.code),
  )
  const hasImportableLegacy = legacyProviders.some(
    (provider) => provider.configured && !managedCodes.has(provider.name),
  )
  const latestReconciliation = reconciliationsQuery.data?.[0]
  const billingCredentialReady =
    Boolean(billingAccessToken.trim()) &&
    (editing?.kind !== "new_api" ||
      (Number.isInteger(Number(billingUserId)) && Number(billingUserId) >= 1))

  return (
    <section className="rounded-2xl bg-card p-6 shadow-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold">外部调用通道</h3>
          <p className="mt-1 text-muted-foreground text-sm">
            统一管理官方接口和已获授权的中转，密钥加密保存在服务器。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {hasImportableLegacy && (
            <LoadingButton
              variant="outline"
              size="sm"
              loading={importMutation.isPending}
              onClick={() => importMutation.mutate()}
            >
              <Download />
              纳管现有配置
            </LoadingButton>
          )}
          <Button variant="outline" size="sm" onClick={openCreate}>
            <Plus />
            添加通道
          </Button>
        </div>
      </div>

      <div className="mt-5 divide-y border-y">
        {(channelsQuery.data?.data ?? []).map((channel, index) => {
          const mappings = channelMappings[index]?.data ?? []
          return (
            <div
              key={channel.id}
              className="grid gap-3 py-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(16rem,1fr)_auto] lg:items-center"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-sm">
                    {channel.display_name}
                  </span>
                  <Tag
                    variant={channel.status === "active" ? "mint" : "neutral"}
                  >
                    {CHANNEL_STATUS_LABELS[channel.status]}
                  </Tag>
                  <Tag
                    variant={
                      channel.health_status === "healthy"
                        ? "mint"
                        : channel.health_status === "open" ||
                            channel.health_status === "disabled"
                          ? "red"
                          : "amber"
                    }
                  >
                    {HEALTH_LABELS[channel.health_status ?? "unknown"]}
                  </Tag>
                </div>
                <p className="mt-1 truncate text-muted-foreground text-xs">
                  {KIND_LABELS[channel.kind]} · {channel.base_url}
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-muted-foreground text-xs">
                  <span className="inline-flex items-center gap-1">
                    <KeyRound className="size-3" />
                    {channel.credential_configured
                      ? `密钥 ····${channel.credential_last_four}`
                      : "未配置密钥"}
                  </span>
                  <span>并发上限 {channel.max_concurrency}</span>
                  <span>超时 {channel.timeout_seconds} 秒</span>
                </div>
              </div>
              <div className="min-w-0">
                <div className="text-muted-foreground text-xs">
                  可用模型（{mappings.length}）
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {mappings.slice(0, 5).map((mapping) => (
                    <Tag
                      key={mapping.id}
                      variant={mapping.enabled ? "neutral" : "amber"}
                    >
                      {mapping.canonical_model}
                    </Tag>
                  ))}
                  {mappings.length > 5 && (
                    <Tag variant="neutral">+{mappings.length - 5}</Tag>
                  )}
                  {!channelMappings[index]?.isPending && !mappings.length && (
                    <span className="text-muted-foreground text-xs">
                      尚未添加模型
                    </span>
                  )}
                </div>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => openEdit(channel)}
              >
                <Settings2 />
                管理
              </Button>
            </div>
          )
        })}
        {!channelsQuery.isPending && !channelsQuery.data?.count && (
          <div className="py-9 text-center">
            <p className="font-medium text-sm">尚未纳管调用通道</p>
            <p className="mt-1 text-muted-foreground text-xs">
              纳管现有配置，或添加新的中转地址和调用密钥。
            </p>
          </div>
        )}
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {editing ? "管理调用通道" : "添加调用通道"}
            </DialogTitle>
            <DialogDescription>
              只接入你有权使用的服务。服务器不会向学校或老师公开这些信息。
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="channel-name">名称</Label>
              <Input
                id="channel-name"
                value={form.displayName}
                onChange={(event) =>
                  setForm({ ...form, displayName: event.target.value })
                }
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="channel-code">渠道代码</Label>
              <Input
                id="channel-code"
                value={form.code}
                disabled={Boolean(editing)}
                placeholder="如 school-relay"
                onChange={(event) =>
                  setForm({ ...form, code: event.target.value })
                }
              />
            </div>
            <div className="grid gap-1.5">
              <Label>类型</Label>
              <Select
                value={form.kind}
                onValueChange={(value: ProviderChannelKind) =>
                  setForm({ ...form, kind: value })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(KIND_LABELS).map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label>接口协议</Label>
              <Select
                value={form.protocol}
                onValueChange={(value: ProviderProtocol) =>
                  setForm({ ...form, protocol: value })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="openai_chat">Chat Completions</SelectItem>
                  <SelectItem value="openai_responses">Responses</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5 sm:col-span-2">
              <Label htmlFor="channel-url">接口地址</Label>
              <Input
                id="channel-url"
                value={form.baseUrl}
                placeholder="https://relay.example.com/v1"
                onChange={(event) =>
                  setForm({ ...form, baseUrl: event.target.value })
                }
              />
            </div>
            <div className="grid gap-1.5 sm:col-span-2">
              <Label htmlFor="channel-key">
                {editing ? "更换调用密钥（留空不变）" : "调用密钥"}
              </Label>
              <Input
                id="channel-key"
                type="password"
                autoComplete="new-password"
                value={form.apiKey}
                onChange={(event) =>
                  setForm({ ...form, apiKey: event.target.value })
                }
              />
              {editing?.credential_configured && (
                <p className="text-muted-foreground text-xs">
                  当前密钥 ····{editing.credential_last_four}
                  ，完整密钥不会回显；输入新值后将安全轮换。
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="channel-concurrency">通道并发上限</Label>
              <Input
                id="channel-concurrency"
                type="number"
                min={1}
                max={128}
                value={form.maxConcurrency}
                onChange={(event) =>
                  setForm({ ...form, maxConcurrency: event.target.value })
                }
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="channel-timeout">超时秒数</Label>
              <Input
                id="channel-timeout"
                type="number"
                min={5}
                max={600}
                value={form.timeoutSeconds}
                onChange={(event) =>
                  setForm({ ...form, timeoutSeconds: event.target.value })
                }
              />
            </div>
          </div>

          <div className="flex flex-wrap gap-x-6 gap-y-3 border-y py-4 text-sm">
            <div className="grid min-w-44 gap-1.5">
              <Label>运行状态</Label>
              <Select
                value={form.status}
                onValueChange={(status: ProviderChannelStatus) =>
                  setForm({ ...form, status })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(CHANNEL_STATUS_LABELS).map(
                    ([value, label]) => (
                      <SelectItem key={value} value={value}>
                        {label}
                      </SelectItem>
                    ),
                  )}
                </SelectContent>
              </Select>
              <p className="text-muted-foreground text-xs">
                排空中不接新请求；已停用立即退出调度。
              </p>
            </div>
            {riskKind && (
              <label htmlFor="channel-risk" className="flex items-center gap-2">
                <Checkbox
                  id="channel-risk"
                  checked={form.riskAcknowledged}
                  onCheckedChange={(checked) =>
                    setForm({ ...form, riskAcknowledged: Boolean(checked) })
                  }
                />
                已确认授权与合规风险
              </label>
            )}
          </div>

          {editing && (
            <div>
              <div className="flex items-end justify-between gap-3">
                <div>
                  <h4 className="font-medium text-sm">可用模型</h4>
                  <p className="mt-1 text-muted-foreground text-xs">
                    标准模型供点凡内部路由使用，上游模型必须与中转实际名称一致。
                  </p>
                </div>
                <LoadingButton
                  type="button"
                  variant="outline"
                  size="sm"
                  loading={discoverMutation.isPending}
                  onClick={() => discoverMutation.mutate()}
                >
                  <RefreshCw />
                  读取上游模型
                </LoadingButton>
              </div>
              {discoveredModels !== null && (
                <div className="mt-3 border-y bg-muted/20">
                  <div className="flex items-center justify-between px-2 py-2 text-xs">
                    <span className="font-medium">上游返回的模型</span>
                    <span className="text-muted-foreground">
                      {discoveredModels.length} 个
                    </span>
                  </div>
                  <div className="max-h-48 divide-y overflow-y-auto border-t">
                    {discoveredModels.map((model) => {
                      const configured = (mappingsQuery.data ?? []).some(
                        (mapping) => mapping.upstream_model === model,
                      )
                      return (
                        <div
                          key={model}
                          className="flex min-w-0 items-center justify-between gap-3 px-2 py-2"
                        >
                          <span className="truncate font-mono text-xs">
                            {model}
                          </span>
                          {configured ? (
                            <Tag variant="mint">已加入</Tag>
                          ) : (
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              onClick={() => {
                                setCanonicalModel(model)
                                setUpstreamModel(model)
                              }}
                            >
                              选用
                            </Button>
                          )}
                        </div>
                      )
                    })}
                    {!discoveredModels.length && (
                      <div className="px-2 py-5 text-center text-muted-foreground text-xs">
                        上游未返回可用模型
                      </div>
                    )}
                  </div>
                </div>
              )}
              <div className="mt-2 divide-y border-y">
                {(mappingsQuery.data ?? []).map((mapping) => (
                  <div
                    key={mapping.id}
                    className="grid gap-3 py-3 text-sm sm:grid-cols-[minmax(8rem,.8fr)_minmax(10rem,1fr)_auto] sm:items-center"
                  >
                    <div className="min-w-0">
                      <div className="truncate font-medium">
                        {mapping.canonical_model}
                      </div>
                      <label
                        htmlFor={`mapping-enabled-${mapping.id}`}
                        className="mt-1 flex items-center gap-2 text-muted-foreground text-xs"
                      >
                        <Checkbox
                          id={`mapping-enabled-${mapping.id}`}
                          checked={mapping.enabled}
                          disabled={mappingUpdateMutation.isPending}
                          onCheckedChange={(checked) =>
                            mappingUpdateMutation.mutate({
                              mapping,
                              patch: { enabled: Boolean(checked) },
                            })
                          }
                        />
                        {mapping.enabled ? "已启用" : "已停用"}
                      </label>
                      {testResults[mapping.id] && (
                        <p
                          className={`mt-1 text-xs ${
                            testResults[mapping.id].ok
                              ? "text-emerald-600 dark:text-emerald-400"
                              : "text-destructive"
                          }`}
                        >
                          {testResults[mapping.id].ok
                            ? `正常 · ${((testResults[mapping.id].latency_ms ?? 0) / 1000).toFixed(1)} 秒`
                            : `失败 · ${testResults[mapping.id].error || "连接检测未通过"}`}
                        </p>
                      )}
                      {!testResults[mapping.id] &&
                        mapping.usage_metering_verified && (
                          <p className="mt-1 text-emerald-600 text-xs dark:text-emerald-400">
                            已验证返回可计费用量
                          </p>
                        )}
                    </div>
                    <div className="grid gap-1.5">
                      <Label htmlFor={`upstream-${mapping.id}`}>
                        上游模型名
                      </Label>
                      <div className="flex gap-1.5">
                        <Input
                          id={`upstream-${mapping.id}`}
                          className="h-8"
                          value={
                            mappingDrafts[mapping.id] ?? mapping.upstream_model
                          }
                          onChange={(event) =>
                            setMappingDrafts((current) => ({
                              ...current,
                              [mapping.id]: event.target.value,
                            }))
                          }
                        />
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={
                            mappingUpdateMutation.isPending ||
                            !mappingDrafts[mapping.id]?.trim() ||
                            mappingDrafts[mapping.id] === mapping.upstream_model
                          }
                          onClick={() =>
                            mappingUpdateMutation.mutate({
                              mapping,
                              patch: {
                                upstream_model: (
                                  mappingDrafts[mapping.id] ?? ""
                                ).trim(),
                              },
                            })
                          }
                        >
                          保存
                        </Button>
                      </div>
                      <div className="flex flex-wrap gap-3 text-muted-foreground text-xs">
                        <label
                          htmlFor={`mapping-vision-${mapping.id}`}
                          className="flex items-center gap-1.5"
                        >
                          <Checkbox
                            id={`mapping-vision-${mapping.id}`}
                            checked={mapping.supports_vision}
                            disabled={mappingUpdateMutation.isPending}
                            onCheckedChange={(checked) =>
                              mappingUpdateMutation.mutate({
                                mapping,
                                patch: { supports_vision: Boolean(checked) },
                              })
                            }
                          />
                          图片输入
                        </label>
                        <label
                          htmlFor={`mapping-structured-${mapping.id}`}
                          className="flex items-center gap-1.5"
                        >
                          <Checkbox
                            id={`mapping-structured-${mapping.id}`}
                            checked={mapping.supports_structured_output}
                            disabled={mappingUpdateMutation.isPending}
                            onCheckedChange={(checked) =>
                              mappingUpdateMutation.mutate({
                                mapping,
                                patch: {
                                  supports_structured_output: Boolean(checked),
                                },
                              })
                            }
                          />
                          结构化输出
                        </label>
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-1">
                      <LoadingButton
                        variant="ghost"
                        size="sm"
                        className="min-w-20"
                        loading={testingMappingId === mapping.id}
                        disabled={testMutation.isPending}
                        onClick={() =>
                          testMutation.mutate({
                            mappingId: mapping.id,
                            model: mapping.canonical_model,
                          })
                        }
                      >
                        {testingMappingId !== mapping.id && <RotateCw />}
                        {testingMappingId === mapping.id ? "检测中" : "检测"}
                      </LoadingButton>
                    </div>
                  </div>
                ))}
                {!mappingsQuery.isPending && !mappingsQuery.data?.length && (
                  <div className="py-6 text-center text-muted-foreground text-xs">
                    尚未添加模型映射
                  </div>
                )}
              </div>
              <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                <Input
                  placeholder="标准模型名"
                  value={canonicalModel}
                  onChange={(event) => setCanonicalModel(event.target.value)}
                />
                <Input
                  placeholder="上游模型名"
                  value={upstreamModel}
                  onChange={(event) => setUpstreamModel(event.target.value)}
                />
                <LoadingButton
                  variant="outline"
                  loading={mappingMutation.isPending}
                  disabled={!canonicalModel.trim() || !upstreamModel.trim()}
                  onClick={() => mappingMutation.mutate()}
                >
                  添加映射
                </LoadingButton>
              </div>
              <div className="mt-3 flex flex-wrap gap-5 text-sm">
                <label
                  htmlFor="mapping-supports-vision"
                  className="flex items-center gap-2"
                >
                  <Checkbox
                    id="mapping-supports-vision"
                    checked={supportsVision}
                    onCheckedChange={(checked) =>
                      setSupportsVision(Boolean(checked))
                    }
                  />
                  支持图片输入
                </label>
                <label
                  htmlFor="mapping-supports-structured"
                  className="flex items-center gap-2"
                >
                  <Checkbox
                    id="mapping-supports-structured"
                    checked={supportsStructuredOutput}
                    onCheckedChange={(checked) =>
                      setSupportsStructuredOutput(Boolean(checked))
                    }
                  />
                  支持结构化输出
                </label>
              </div>
              <p className="mt-2 text-muted-foreground text-xs">
                同一通道共用一个密钥，可连续添加 Claude、Gemini、GPT
                等多条模型映射；单模型密钥只添加一条即可。修改接口地址或密钥后，请先保存通道再读取。
              </p>
              <div
                className="mt-5 border-t pt-4"
                data-testid="channel-billing-reconciliation"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h4 className="font-medium text-sm">供应商账单对账</h4>
                    <p className="text-muted-foreground text-xs">
                      用上游实际扣费核对本地成本估算。
                    </p>
                  </div>
                  {latestReconciliation && (
                    <Tag
                      variant={
                        latestReconciliation.mismatch_count ? "amber" : "mint"
                      }
                    >
                      最近异常 {latestReconciliation.mismatch_count} 条
                    </Tag>
                  )}
                </div>

                <div className="mt-3 border-y">
                  <div
                    className={`grid gap-3 bg-muted/20 px-3 py-3 sm:items-end ${
                      editing.kind === "new_api"
                        ? "sm:grid-cols-[minmax(0,1fr)_8rem_auto]"
                        : "sm:grid-cols-[minmax(0,1fr)_auto]"
                    }`}
                  >
                    <div className="grid gap-1.5">
                      <Label htmlFor="billing-access-token">
                        {editing.kind === "new_api"
                          ? "账单查询密钥（系统访问令牌）"
                          : "账单查询密钥"}
                      </Label>
                      <Input
                        id="billing-access-token"
                        type="password"
                        autoComplete="new-password"
                        value={billingAccessToken}
                        placeholder={
                          editing.billing_credential_configured
                            ? `已配置 ····${editing.billing_credential_last_four}`
                            : editing.kind === "new_api"
                              ? "New API 个人设置中的系统访问令牌"
                              : "供应商提供的账单查询密钥"
                        }
                        onChange={(event) =>
                          setBillingAccessToken(event.target.value)
                        }
                      />
                    </div>
                    {editing.kind === "new_api" && (
                      <div className="grid gap-1.5">
                        <Label htmlFor="billing-user-id">用户 ID</Label>
                        <Input
                          id="billing-user-id"
                          type="number"
                          min={1}
                          value={billingUserId}
                          placeholder="New-Api-User"
                          onChange={(event) =>
                            setBillingUserId(event.target.value)
                          }
                        />
                      </div>
                    )}
                    <LoadingButton
                      type="button"
                      variant="outline"
                      size="sm"
                      loading={billingCredentialMutation.isPending}
                      disabled={!billingCredentialReady}
                      onClick={() => billingCredentialMutation.mutate()}
                    >
                      保存账单凭据
                    </LoadingButton>
                    <p
                      className={`text-muted-foreground text-xs ${
                        editing.kind === "new_api"
                          ? "sm:col-span-3"
                          : "sm:col-span-2"
                      }`}
                    >
                      {editing.kind === "new_api"
                        ? "与模型调用密钥分开保存。用户 ID 可在浏览器开发者工具任一 New API 请求的 New-Api-User 请求头中查看。"
                        : "与模型调用密钥分开加密保存；供应商账单接口接入后用于自动查询。"}
                    </p>
                  </div>
                  {editing.kind === "new_api" && (
                    <>
                      <div className="flex flex-wrap items-center justify-between gap-3 border-t px-3 py-3">
                        <div className="flex min-w-0 items-center gap-2.5">
                          <ReceiptText className="size-4 shrink-0 text-muted-foreground" />
                          <div className="min-w-0">
                            <p className="font-medium text-sm">
                              {latestReconciliation?.upstream_system_name ??
                                editing.display_name}
                              {latestReconciliation?.upstream_version
                                ? ` · ${latestReconciliation.upstream_version}`
                                : ""}
                            </p>
                            <p className="mt-0.5 text-muted-foreground text-xs">
                              {!editing.billing_credential_configured
                                ? "配置账单凭据后可读取账号级账单"
                                : latestReconciliation
                                  ? `账号累计实付 ¥${latestReconciliation.upstream_total_used_rmb.toLocaleString("zh-CN", { maximumFractionDigits: 4 })}`
                                  : "尚未读取上游账单"}
                            </p>
                          </div>
                        </div>
                        <LoadingButton
                          type="button"
                          size="sm"
                          loading={newApiSyncMutation.isPending}
                          disabled={
                            !editing.billing_credential_configured ||
                            !editing.billing_user_id
                          }
                          onClick={() => newApiSyncMutation.mutate()}
                          data-testid="sync-new-api-billing"
                        >
                          {!newApiSyncMutation.isPending && <RefreshCw />}
                          同步 New API 账单
                        </LoadingButton>
                      </div>
                      {latestReconciliation && (
                        <div className="grid grid-cols-2 border-t text-xs sm:grid-cols-4">
                          {[
                            ["上游记录", latestReconciliation.fetched_count],
                            ["本次认领", latestReconciliation.row_count],
                            [
                              "外部或已同步",
                              latestReconciliation.ignored_count,
                            ],
                            ["差异", latestReconciliation.mismatch_count],
                          ].map(([label, value], index) => (
                            <div
                              key={label}
                              className={`px-3 py-2.5 ${
                                index % 2 === 0 ? "border-r" : ""
                              } sm:border-r sm:last:border-r-0`}
                            >
                              <p className="text-muted-foreground">{label}</p>
                              <p className="mt-0.5 font-semibold tabular-nums">
                                {value} 条
                              </p>
                            </div>
                          ))}
                        </div>
                      )}
                      <p className="border-t px-3 py-2 text-muted-foreground text-xs">
                        共用密钥产生的其他系统记录不会计入点凡阅卷成本。
                      </p>
                    </>
                  )}
                </div>

                <details className="mt-3 text-sm">
                  <summary className="cursor-pointer select-none text-muted-foreground hover:text-foreground">
                    {editing.kind === "new_api"
                      ? "手动导入账单（备用）"
                      : "手动导入账单"}
                  </summary>
                  <p className="mt-2 text-muted-foreground text-xs">
                    每行：请求编号,输入 Token,输出 Token,成本人民币
                  </p>
                  <textarea
                    aria-label="对账 CSV"
                    className="mt-2 min-h-24 w-full rounded-md border bg-background px-3 py-2 font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    placeholder="req_123,1200,300,0.025"
                    value={reconciliationCsv}
                    onChange={(event) =>
                      setReconciliationCsv(event.target.value)
                    }
                  />
                  <div className="mt-2 flex justify-end">
                    <LoadingButton
                      type="button"
                      variant="outline"
                      size="sm"
                      loading={reconciliationMutation.isPending}
                      disabled={!reconciliationCsv.trim()}
                      onClick={() => reconciliationMutation.mutate()}
                    >
                      导入并对账
                    </LoadingButton>
                  </div>
                </details>
              </div>
            </div>
          )}

          <DialogFooter>
            <Button variant="ghost" onClick={() => setDialogOpen(false)}>
              取消
            </Button>
            <LoadingButton
              loading={saveMutation.isPending}
              disabled={
                !canSave ||
                (riskKind && form.status === "active" && !form.riskAcknowledged)
              }
              onClick={() => saveMutation.mutate()}
            >
              保存通道
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}
