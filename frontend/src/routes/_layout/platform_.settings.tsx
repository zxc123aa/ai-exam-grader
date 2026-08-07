import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link as RouterLink } from "@tanstack/react-router"
import { ArrowRight } from "lucide-react"
import { useEffect, useState } from "react"

import { PlatformService } from "@/client"
import { PageHead } from "@/components/Common/PageHead"
import { ModelOfferingsSection } from "@/components/Platform/ModelOfferingsSection"
import { requirePlatformSuperuser } from "@/components/Platform/orgMeta"
import { ProviderChannelsSection } from "@/components/Platform/ProviderChannelsSection"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import { Skeleton } from "@/components/ui/skeleton"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/platform_/settings")({
  component: PlatformSettings,
  beforeLoad: requirePlatformSuperuser,
  head: () => ({
    meta: [
      {
        title: "中转与方案 - 点凡阅卷",
      },
    ],
  }),
})

const CARD_CLASS = "rounded-2xl bg-card p-6 shadow-card"

function PlatformSettings() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const { data: config, isPending } = useQuery({
    queryKey: ["platform-system-config"],
    queryFn: () => PlatformService.readSystemConfig(),
  })
  const { data: billingRates = [] } = useQuery({
    queryKey: ["platform-billing-rates"],
    queryFn: () => PlatformService.listBillingRates(),
  })

  const [reviewThreshold, setReviewThreshold] = useState(
    String(config?.review_threshold ?? ""),
  )
  const [maxConcurrency, setMaxConcurrency] = useState(
    String(config?.max_concurrency ?? ""),
  )
  const [rateVersion, setRateVersion] = useState("")
  const [rateInput, setRateInput] = useState("")
  const [rateOutput, setRateOutput] = useState("")
  const [rateImage, setRateImage] = useState("")
  const [costInput, setCostInput] = useState("")
  const [costOutput, setCostOutput] = useState("")
  const [costImage, setCostImage] = useState("")

  useEffect(() => {
    if (!config) return
    setReviewThreshold(String(config.review_threshold))
    setMaxConcurrency(String(config.max_concurrency))
  }, [config])

  const mutation = useMutation({
    mutationFn: () =>
      PlatformService.updateSystemConfig({
        requestBody: {
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

  const rateMutation = useMutation({
    mutationFn: () =>
      PlatformService.createBillingRate({
        requestBody: {
          version: rateVersion.trim(),
          effective_at: new Date().toISOString(),
          input_credits_per_million: Number(rateInput),
          output_credits_per_million: Number(rateOutput),
          image_credits_per_million: Number(rateImage),
          internal_input_rmb_per_million: Number(costInput || 0),
          internal_output_rmb_per_million: Number(costOutput || 0),
          internal_image_rmb_per_million: Number(costImage || 0),
        },
      }),
    onSuccess: () => {
      showSuccessToast("费率版本已创建")
      setRateVersion("")
      setRateInput("")
      setRateOutput("")
      setRateImage("")
      setCostInput("")
      setCostOutput("")
      setCostImage("")
      queryClient.invalidateQueries({ queryKey: ["platform-billing-rates"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  if (isPending || !config) {
    return (
      <div className="flex flex-col gap-6">
        <PageHead
          title="中转与方案"
          subtitle="维护上游调用通道、学校可选方案和计费规则"
        />
        <Skeleton className="h-44 rounded-2xl" />
        <Skeleton className="h-32 rounded-2xl" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6" data-testid="platform-settings-page">
      <PageHead
        title="中转与方案"
        subtitle="维护上游调用通道、学校可选方案和计费规则"
      />

      <ProviderChannelsSection legacyProviders={config.providers} />

      <ModelOfferingsSection />

      <section className={CARD_CLASS}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold">功能与模型调度</h3>
            <p className="mt-1 text-muted-foreground text-sm">
              模型用途、主备通道和分流权重已统一到独立控制页。
            </p>
          </div>
          <Button variant="outline" size="sm" asChild>
            <RouterLink to="/platform/routing">
              打开功能调度
              <ArrowRight />
            </RouterLink>
          </Button>
        </div>
      </section>

      <section className={CARD_CLASS}>
        <h3 className="font-semibold">批改运行默认值</h3>
        <p className="mt-1 text-muted-foreground text-sm">
          控制新批次的复核敏感度与任务并发；具体模型和通道由功能调度决定。
        </p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
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
              max={32}
              step={1}
              value={maxConcurrency}
              onChange={(e) => setMaxConcurrency(e.target.value)}
            />
          </div>
        </div>
        <div className="mt-4">
          <LoadingButton
            data-testid="platform-settings-save"
            loading={mutation.isPending}
            disabled={!reviewThreshold || !maxConcurrency}
            onClick={() => mutation.mutate()}
          >
            保存运行默认值
          </LoadingButton>
        </div>
      </section>

      <section className={CARD_CLASS}>
        <h3 className="font-semibold">计费标准</h3>
        <p className="mt-1 text-muted-foreground text-sm">
          每个合同固定引用一个费率版本；版本创建后不可修改，只能新增后续版本。
        </p>
        {billingRates.length > 0 && (
          <div className="mt-4 divide-y border-y text-sm">
            {billingRates.map((rate) => (
              <div
                key={rate.id}
                className="grid gap-2 py-3 sm:grid-cols-[1fr_auto] sm:items-center"
              >
                <div>
                  <span className="font-medium">{rate.version}</span>
                  <span className="ml-2 text-muted-foreground">
                    {new Date(rate.effective_at).toLocaleDateString("zh-CN")}{" "}
                    生效
                  </span>
                </div>
                <span className="text-muted-foreground tabular-nums">
                  输入 {rate.input_microcredits_per_million / 1_000_000} / 输出{" "}
                  {rate.output_microcredits_per_million / 1_000_000} / 图片{" "}
                  {rate.image_microcredits_per_million / 1_000_000} 积分/百万
                  Token
                </span>
              </div>
            ))}
          </div>
        )}
        <div className="mt-5 grid gap-4 sm:grid-cols-4">
          <div className="grid gap-1.5">
            <Label htmlFor="rate-version">版本名称</Label>
            <Input
              id="rate-version"
              placeholder="如 2026-v1"
              value={rateVersion}
              onChange={(event) => setRateVersion(event.target.value)}
            />
          </div>
          {[
            ["输入积分/百万 Token", rateInput, setRateInput],
            ["输出积分/百万 Token", rateOutput, setRateOutput],
            ["图片积分/百万 Token", rateImage, setRateImage],
          ].map(([label, value, setter]) => (
            <div key={label as string} className="grid gap-1.5">
              <Label>{label as string}</Label>
              <Input
                type="number"
                min={0}
                value={value as string}
                onChange={(event) =>
                  (setter as (value: string) => void)(event.target.value)
                }
              />
            </div>
          ))}
          {[
            ["输入内部成本（元）", costInput, setCostInput],
            ["输出内部成本（元）", costOutput, setCostOutput],
            ["图片内部成本（元）", costImage, setCostImage],
          ].map(([label, value, setter]) => (
            <div key={label as string} className="grid gap-1.5">
              <Label>{label as string}</Label>
              <Input
                type="number"
                min={0}
                value={value as string}
                onChange={(event) =>
                  (setter as (value: string) => void)(event.target.value)
                }
              />
            </div>
          ))}
          <div className="flex items-end">
            <LoadingButton
              variant="outline"
              loading={rateMutation.isPending}
              disabled={
                !rateVersion.trim() ||
                rateInput === "" ||
                rateOutput === "" ||
                rateImage === ""
              }
              onClick={() => rateMutation.mutate()}
            >
              新建费率版本
            </LoadingButton>
          </div>
        </div>
      </section>
    </div>
  )
}

export default PlatformSettings
