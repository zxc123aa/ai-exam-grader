import { useState } from "react"

const RUN_SETTINGS_KEY = "dianfan.grading-settings.v2"
const LEGACY_RUN_SETTINGS_KEY = "dianfan.grading-settings"

export type RunSettings = {
  provider: string
  model: string
  threshold: string
  parallelSubmissions: string
  concurrencyPerSubmission: string
}

export const DEFAULT_RUN_SETTINGS: RunSettings = {
  provider: "pomoai",
  model: "gpt-5.6-sol",
  threshold: "0.8",
  parallelSubmissions: "8",
  concurrencyPerSubmission: "4",
}

function loadRunSettings(): RunSettings {
  try {
    const raw = localStorage.getItem(RUN_SETTINGS_KEY)
    if (raw) {
      return { ...DEFAULT_RUN_SETTINGS, ...(JSON.parse(raw) as RunSettings) }
    }
    const legacyRaw = localStorage.getItem(LEGACY_RUN_SETTINGS_KEY)
    if (!legacyRaw) return DEFAULT_RUN_SETTINGS
    const legacy = JSON.parse(legacyRaw) as RunSettings
    return {
      ...DEFAULT_RUN_SETTINGS,
      provider: legacy.provider || DEFAULT_RUN_SETTINGS.provider,
      model: legacy.model || DEFAULT_RUN_SETTINGS.model,
      threshold: legacy.threshold || DEFAULT_RUN_SETTINGS.threshold,
    }
  } catch {
    return DEFAULT_RUN_SETTINGS
  }
}

/**
 * 批改设置（判题模型/阈值/两级并发）：老师在「批改设置」抽屉或
 * 「高级设置」页修改，对之后发起的批改批次生效。
 * 两处共享同一份 localStorage 配置。
 */
export function useRunSettings() {
  const [runSettings, setRunSettings] = useState<RunSettings>(loadRunSettings)

  const patchRunSettings = (patch: Partial<RunSettings>) => {
    setRunSettings((current) => {
      const next = { ...current, ...patch }
      localStorage.setItem(RUN_SETTINGS_KEY, JSON.stringify(next))
      return next
    })
  }

  const resetRunSettings = () => {
    localStorage.removeItem(RUN_SETTINGS_KEY)
    localStorage.removeItem(LEGACY_RUN_SETTINGS_KEY)
    setRunSettings(DEFAULT_RUN_SETTINGS)
  }

  return { runSettings, patchRunSettings, resetRunSettings }
}
