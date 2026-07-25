import type { LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

/**
 * 统计卡（点凡阅卷 原型 stat-card 同款）。
 * tone 图标块 + 大数值（带小单位）+ 标签 + 脚注；
 * 传 ring 时右上角显示 SVG 环形进度。
 * tone 类名全部以字面量写在映射表里，保证 Tailwind 能扫描到。
 */
export type StatTone = "indigo" | "violet" | "mint" | "amber" | "sky" | "pink"

const TONE_CLASSES: Record<StatTone, { icon: string; ring: string }> = {
  // 图标块统一中性色（视觉规范：不每张卡片一个彩色图标）；
  // ring 保留语义色——它表达的是进度/状态数据，不是装饰
  indigo: { icon: "bg-secondary text-muted-foreground", ring: "#2E5BFF" },
  violet: { icon: "bg-secondary text-muted-foreground", ring: "#8B5CF6" },
  mint: { icon: "bg-secondary text-muted-foreground", ring: "#10B981" },
  amber: { icon: "bg-secondary text-muted-foreground", ring: "#F59E0B" },
  sky: { icon: "bg-secondary text-muted-foreground", ring: "#38BDF8" },
  pink: { icon: "bg-secondary text-muted-foreground", ring: "#F472B6" },
}

export function StatCard({
  icon: Icon,
  tone = "indigo",
  value,
  unit,
  label,
  foot,
  ring,
  className,
}: {
  icon: LucideIcon
  tone?: StatTone
  /** 大数值（已格式化字符串或数字） */
  value: string | number
  /** 数值后的小单位，如 "份"、"%" */
  unit?: string
  label: string
  /** 脚注 muted 文本 */
  foot?: string
  /** 环形进度 0-100，传入则替代/伴随图标显示 */
  ring?: number
  className?: string
}) {
  const t = TONE_CLASSES[tone]
  return (
    <div
      className={cn(
        "rounded-2xl border bg-card p-5 shadow-card transition-all duration-200 hover:-translate-y-0.5 hover:shadow-card-lg",
        className,
      )}
    >
      <div className="mb-3 flex items-center justify-between">
        <span
          className={cn(
            "inline-flex size-11 items-center justify-center rounded-xl",
            t.icon,
          )}
        >
          <Icon className="size-5" />
        </span>
        {ring != null && <StatRing value={ring} color={t.ring} />}
      </div>
      <p className="font-bold text-3xl tracking-tight tabular-nums">
        {value}
        {unit && (
          <small className="ml-1 font-semibold text-muted-foreground text-sm">
            {unit}
          </small>
        )}
      </p>
      <p className="mt-0.5 font-medium text-secondary-foreground text-sm">
        {label}
      </p>
      {foot && <p className="mt-1.5 text-muted-foreground text-xs">{foot}</p>}
    </div>
  )
}

/** 统计卡右上角的小环形进度（SVG circle + strokeDasharray，无第三方依赖） */
function StatRing({ value, color }: { value: number; color: string }) {
  const size = 56
  const stroke = 6
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const v = Math.min(100, Math.max(0, value))
  return (
    <span
      className="relative inline-flex"
      style={{ width: size, height: size }}
    >
      <svg width={size} height={size} role="presentation">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          strokeWidth={stroke}
          className="stroke-secondary"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${((v / 100) * c).toFixed(1)} ${c.toFixed(1)}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center font-semibold text-[11px] tabular-nums">
        {Math.round(v)}%
      </span>
    </span>
  )
}
