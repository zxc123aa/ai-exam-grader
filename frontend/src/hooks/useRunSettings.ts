import { useState } from "react"

const RUN_SETTINGS_KEY = "dianfan.grading-settings"

export type RunSettings = {
  provider: string
  model: string
  threshold: string
  maxConcurrency: string
}

export const DEFAULT_RUN_SETTINGS: RunSettings = {
  provider: "pomoai",
  model: "gpt-5.6-sol",
  threshold: "0.8",
  maxConcurrency: "8",
}

function loadRunSettings(): RunSettings {
  try {
    const raw = localStorage.getItem(RUN_SETTINGS_KEY)
    return raw
      ? { ...DEFAULT_RUN_SETTINGS, ...(JSON.parse(raw) as RunSettings) }
      : DEFAULT_RUN_SETTINGS
  } catch {
    return DEFAULT_RUN_SETTINGS
  }
}

/**
 * 批改设置（判题模型/阈值/并发）：老师在「批改设置」抽屉或
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
    setRunSettings(DEFAULT_RUN_SETTINGS)
  }

  return { runSettings, patchRunSettings, resetRunSettings }
}
