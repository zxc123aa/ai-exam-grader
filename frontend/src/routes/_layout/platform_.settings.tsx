import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useEffect, useState } from "react"

import { PlatformService } from "@/client"
import { PageHead } from "@/components/Common/PageHead"
import { Tag } from "@/components/Common/Tag"
import { requirePlatformSuperuser } from "@/components/Platform/orgMeta"
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

export const Route = createFileRoute("/_layout/platform_/settings")({
  component: PlatformSettings,
  beforeLoad: requirePlatformSuperuser,
  head: () => ({
    meta: [
      {
        title: "系统设置 - 点凡阅卷",
      },
    ],
  }),
})

const CARD_CLASS = "rounded-2xl bg-card p-6 shadow-card"

// 与批改工作台 / 标准答案页的 providerModels 保持一致；
// 后端 services/system_config.py 会按同一映射校验组合。
const providerModels: Record<string, string[]> = {
  pomoai: [
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "grok-4.5",
    "gemini-3.5-flash",
  ],
  fluxnode_gemini: ["gemini-3.5-flash"],
  fluxnode_grok: ["grok-4.5"],
  kimi: [
    "kimi-k3",
    "kimi-k2.7-code",
    "kimi-k2.7-code-highspeed",
    "kimi-k2.6",
    "kimi-k2.5",
  ],
}

function ProviderModelSelects({
  idPrefix,
  provider,
  model,
  onProviderChange,
  onModelChange,
}: {
  idPrefix: string
  provider: string
  model: string
  onProviderChange: (value: string) => void
  onModelChange: (value: string) => void
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="grid gap-1.5">
        <Label htmlFor={`${idPrefix}-provider`}>服务商</Label>
        <Select value={provider} onValueChange={onProviderChange}>
          <SelectTrigger id={`${idPrefix}-provider`}>
            <SelectValue placeholder="选择服务商" />
          </SelectTrigger>
          <SelectContent>
            {Object.keys(providerModels).map((value) => (
              <SelectItem key={value} value={value}>
                {value}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor={`${idPrefix}-model`}>模型</Label>
        <Select value={model} onValueChange={onModelChange}>
          <SelectTrigger id={`${idPrefix}-model`}>
            <SelectValue placeholder="选择模型" />
          </SelectTrigger>
          <SelectContent>
            {(providerModels[provider] ?? []).map((value) => (
              <SelectItem key={value} value={value}>
                {value}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  )
}

function PlatformSettings() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const { data: config, isPending } = useQuery({
    queryKey: ["platform-system-config"],
    queryFn: () => PlatformService.readSystemConfig(),
  })

  const [regionProvider, setRegionProvider] = useState("")
  const [regionModel, setRegionModel] = useState("")
  const [recognitionProvider, setRecognitionProvider] = useState("")
  const [recognitionModel, setRecognitionModel] = useState("")
  const [visionProvider, setVisionProvider] = useState("")
  const [visionModel, setVisionModel] = useState("")
  const [gradingProvider, setGradingProvider] = useState("")
  const [gradingModel, setGradingModel] = useState("")
  const [fallbackModels, setFallbackModels] = useState("")
  const [reviewThreshold, setReviewThreshold] = useState("")
  const [maxConcurrency, setMaxConcurrency] = useState("")

  useEffect(() => {
    if (config) {
      setRegionProvider(config.region_provider)
      setRegionModel(config.region_model)
      setRecognitionProvider(config.recognition_provider)
      setRecognitionModel(config.recognition_model)
      setVisionProvider(config.vision_provider)
      setVisionModel(config.vision_model)
      setGradingProvider(config.grading_provider)
      setGradingModel(config.grading_model)
      setFallbackModels(config.fallback_models.join(", "))
      setReviewThreshold(String(config.review_threshold))
      setMaxConcurrency(String(config.max_concurrency))
    }
  }, [config])

  const mutation = useMutation({
    mutationFn: () =>
      PlatformService.updateSystemConfig({
        requestBody: {
          region_provider: regionProvider,
          region_model: regionModel,
          recognition_provider: recognitionProvider,
          recognition_model: recognitionModel,
          vision_provider: visionProvider,
          vision_model: visionModel,
          grading_provider: gradingProvider,
          grading_model: gradingModel,
          fallback_models: fallbackModels
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean),
          review_threshold: Number(reviewThreshold),
          max_concurrency: Number(maxConcurrency),
        },
      }),
    onSuccess: () => {
      showSuccessToast("系统设置已保存，对之后的新批改批次生效")
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-system-config"] })
    },
  })

  if (isPending || !config) {
    return (
      <div className="flex flex-col gap-6">
        <PageHead
          title="系统设置"
          subtitle="判题与识别服务配置，对之后的新批改批次生效"
        />
        <Skeleton className="h-44 rounded-2xl" />
        <Skeleton className="h-32 rounded-2xl" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6" data-testid="platform-settings-page">
      <PageHead
        title="系统设置"
        subtitle="判题与识别服务配置，对之后的新批改批次生效"
      />

      <section className={CARD_CLASS}>
        <h3 className="font-semibold">检测题目区域</h3>
        <p className="mt-1 text-muted-foreground text-sm">
          区域校正页的版面分析与题目区域检测默认使用的模型
        </p>
        <div className="mt-4">
          <ProviderModelSelects
            idPrefix="region"
            provider={regionProvider}
            model={regionModel}
            onProviderChange={(value) => {
              setRegionProvider(value)
              setRegionModel(providerModels[value][0])
            }}
            onModelChange={setRegionModel}
          />
        </div>
      </section>

      <section className={CARD_CLASS}>
        <h3 className="font-semibold">识别题目内容</h3>
        <p className="mt-1 text-muted-foreground text-sm">
          从卷面识别题干与结构默认使用的模型
        </p>
        <div className="mt-4">
          <ProviderModelSelects
            idPrefix="recognition"
            provider={recognitionProvider}
            model={recognitionModel}
            onProviderChange={(value) => {
              setRecognitionProvider(value)
              setRecognitionModel(providerModels[value][0])
            }}
            onModelChange={setRecognitionModel}
          />
        </div>
      </section>

      <section className={CARD_CLASS}>
        <h3 className="font-semibold">批改卷子</h3>
        <p className="mt-1 text-muted-foreground text-sm">
          学生答案识别与判分默认使用的模型
        </p>
        <div className="mt-4 grid gap-4">
          <div className="grid gap-1.5">
            <span className="font-medium text-sm">视觉提取</span>
            <ProviderModelSelects
              idPrefix="vision"
              provider={visionProvider}
              model={visionModel}
              onProviderChange={(value) => {
                setVisionProvider(value)
                setVisionModel(providerModels[value][0])
              }}
              onModelChange={setVisionModel}
            />
          </div>
          <div className="grid gap-1.5">
            <span className="font-medium text-sm">判题</span>
            <ProviderModelSelects
              idPrefix="grading"
              provider={gradingProvider}
              model={gradingModel}
              onProviderChange={(value) => {
                setGradingProvider(value)
                setGradingModel(providerModels[value][0])
              }}
              onModelChange={setGradingModel}
            />
          </div>
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <div className="grid gap-1.5 sm:col-span-3">
            <Label htmlFor="fallback-models">备用模型</Label>
            <Input
              id="fallback-models"
              data-testid="fallback-models-input"
              placeholder="如 pomoai/gpt-5.5，多个用逗号分隔"
              value={fallbackModels}
              onChange={(e) => setFallbackModels(e.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="review-threshold">默认复核阈值</Label>
            <Input
              id="review-threshold"
              data-testid="review-threshold-input"
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={reviewThreshold}
              onChange={(e) => setReviewThreshold(e.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="max-concurrency">默认并发</Label>
            <Input
              id="max-concurrency"
              data-testid="max-concurrency-input"
              type="number"
              min={1}
              max={8}
              step={1}
              value={maxConcurrency}
              onChange={(e) => setMaxConcurrency(e.target.value)}
            />
          </div>
        </div>
      </section>

      <section className={CARD_CLASS}>
        <h3 className="font-semibold">服务状态</h3>
        <p className="mt-1 text-muted-foreground text-sm">
          各服务商的 API Key 配置状态，未配置的服务商无法调用
        </p>
        <ul className="mt-4 divide-y" data-testid="provider-status-list">
          {config.providers.map((provider) => (
            <li
              key={provider.name}
              className="flex items-center justify-between py-2.5"
            >
              <span className="text-sm">{provider.name}</span>
              {provider.configured ? (
                <Tag variant="mint">已配置</Tag>
              ) : (
                <Tag variant="amber">未配置 API Key</Tag>
              )}
            </li>
          ))}
        </ul>
      </section>

      <div>
        <LoadingButton
          data-testid="platform-settings-save"
          loading={mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          保存设置
        </LoadingButton>
      </div>
    </div>
  )
}

export default PlatformSettings
