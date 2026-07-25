import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

/**
 * 页头（点凡阅卷 原型 page-head 同款）。
 * 左侧标题 + 副标题，右侧 actions 插槽（按钮/筛选等）。
 */
export function PageHead({
  title,
  subtitle,
  actions,
  className,
}: {
  title: string
  subtitle?: string
  actions?: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "mb-5 flex flex-wrap items-end justify-between gap-4",
        className,
      )}
    >
      <div>
        <h2 className="font-bold text-xl tracking-tight">{title}</h2>
        {subtitle && (
          <p className="mt-1 text-muted-foreground text-sm">{subtitle}</p>
        )}
      </div>
      {actions && (
        <div className="flex flex-wrap items-center gap-2.5">{actions}</div>
      )}
    </div>
  )
}
