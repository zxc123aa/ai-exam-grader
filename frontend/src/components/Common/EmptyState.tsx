import type { LucideIcon } from "lucide-react"
import { Inbox } from "lucide-react"

import { cn } from "@/lib/utils"

/** 空状态：图标 + 标题 + 说明，用于无数据/建设中的页面区块。 */
export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  className,
}: {
  icon?: LucideIcon
  title: string
  description?: string
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed py-14 text-center",
        className,
      )}
    >
      <Icon className="size-8 text-muted-foreground/60" />
      <p className="text-sm font-medium">{title}</p>
      {description && (
        <p className="max-w-sm text-xs text-muted-foreground">{description}</p>
      )}
    </div>
  )
}
