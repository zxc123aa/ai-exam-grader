import { cn } from "@/lib/utils"

/**
 * 置信度色块（点凡阅卷 原型 conf-badge 同款）。
 * value >= 90 绿、>= 80 黄、否则红；等宽数字便于表格对齐。
 */
export function ConfBadge({
  value,
  suffix = "%",
  className,
}: {
  /** 置信度 0-100 */
  value: number
  suffix?: string
  className?: string
}) {
  const level =
    value >= 90
      ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
      : value >= 80
        ? "bg-amber-500/10 text-amber-600 dark:text-amber-400"
        : "bg-red-500/10 text-red-600 dark:text-red-400"
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center rounded-md px-2 py-0.5 font-semibold text-xs tabular-nums",
        level,
        className,
      )}
    >
      {value.toFixed(0)}
      {suffix}
    </span>
  )
}
