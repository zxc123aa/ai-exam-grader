import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useRunSettings } from "@/hooks/useRunSettings"

/** 各判题 provider 的可选模型（与后端 PROVIDER_MODELS 一致） */
export const PROVIDER_MODELS: Record<string, string[]> = {
  pomoai: [
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "grok-4.5",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
  ],
  fluxnode_gemini: ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"],
  fluxnode_grok: ["grok-4.5"],
  kimi: [
    "kimi-k3",
    "kimi-k2.7-code",
    "kimi-k2.7-code-highspeed",
    "kimi-k2.6",
    "kimi-k2.5",
  ],
}

/**
 * 批改设置表单（判题提供者/模型、复核阈值、最大并发）。
 * 配置持久化在浏览器本地，对之后发起的批改批次生效；
 * 「批改设置」抽屉与「高级设置」页共用。
 */
export function RunSettingsForm() {
  const { runSettings, patchRunSettings, resetRunSettings } = useRunSettings()
  const { provider, model, threshold, maxConcurrency } = runSettings

  return (
    <div className="grid gap-4">
      <div className="grid gap-2">
        <Label>答题识别</Label>
        <div className="flex h-9 items-center rounded-md border bg-muted/40 px-3 text-sm">
          智能视觉识别
        </div>
      </div>
      <div className="grid gap-2">
        <Label>判题提供者</Label>
        <select
          className="h-9 rounded-md border bg-background px-3"
          value={provider}
          onChange={(event) => {
            const nextProvider = event.target.value
            patchRunSettings({
              provider: nextProvider,
              model: PROVIDER_MODELS[nextProvider][0],
            })
          }}
        >
          <option value="pomoai">PomoAI</option>
          <option value="fluxnode_gemini">FluxNode · Gemini</option>
          <option value="fluxnode_grok">FluxNode · Grok</option>
          <option value="kimi">Kimi Coding</option>
        </select>
      </div>
      <div className="grid gap-2">
        <Label>判题模型</Label>
        <select
          className="h-9 rounded-md border bg-background px-3"
          value={model}
          onChange={(event) => patchRunSettings({ model: event.target.value })}
        >
          {(PROVIDER_MODELS[provider] ?? []).map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
      </div>
      <div className="grid gap-2">
        <Label>复核阈值</Label>
        <Input
          type="number"
          min="0"
          max="1"
          step="0.05"
          value={threshold}
          onChange={(event) =>
            patchRunSettings({ threshold: event.target.value })
          }
        />
        <p className="text-muted-foreground text-xs">
          低于该置信度的题目会进入人工复核，默认 0.8
        </p>
      </div>
      <div className="grid gap-2">
        <Label>最大并发</Label>
        <Input
          type="number"
          min="1"
          max="8"
          value={maxConcurrency}
          onChange={(event) =>
            patchRunSettings({ maxConcurrency: event.target.value })
          }
        />
      </div>
      <Button
        variant="ghost"
        size="sm"
        className="justify-self-start"
        onClick={resetRunSettings}
      >
        恢复默认
      </Button>
    </div>
  )
}
