import { cn } from "@/lib/utils"

/**
 * 进度条（点凡阅卷 原型 progress 同款，含 slim / striped 变体）。
 * 底轨 secondary，填充主色或 tone 色；striped 为 CSS 斜纹 + 滚动动画。
 */
export type ProgressTone =
  | "indigo"
  | "violet"
  | "mint"
  | "amber"
  | "sky"
  | "pink"

const TONE_FILL: Record<ProgressTone, string> = {
  indigo: "bg-primary",
  violet: "bg-primary/70",
  mint: "bg-emerald-500",
  amber: "bg-amber-500",
  sky: "bg-sky-400",
  pink: "bg-pink-400",
}

export function ProgressBar({
  value,
  slim = false,
  striped = false,
  tone = "indigo",
  className,
}: {
  /** 进度 0-100 */
  value: number
  /** 细条（6px，常用于行内） */
  slim?: boolean
  /** 斜纹动画（进行中任务） */
  striped?: boolean
  tone?: ProgressTone
  className?: string
}) {
  const v = Math.min(100, Math.max(0, value))
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(v)}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cn(
        "w-full overflow-hidden rounded-full bg-secondary",
        slim ? "h-1.5" : "h-2",
        className,
      )}
    >
      <div
        className={cn(
          "h-full rounded-full transition-[width] duration-500",
          striped ? "progress-striped" : TONE_FILL[tone],
        )}
        style={{ width: `${v}%` }}
      />
    </div>
  )
}
