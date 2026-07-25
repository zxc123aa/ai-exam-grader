import { cn } from "@/lib/utils"

/**
 * 状态标签 pill（点凡阅卷 原型 tag-* 同款）。
 * 浅色底 + 同色系文字，用于状态/分类标注。
 */
export type TagVariant =
  | "neutral"
  | "mint"
  | "amber"
  | "sky"
  | "violet"
  | "pink"
  | "red"
  | "indigo"

const VARIANT_CLASSES: Record<TagVariant, string> = {
  // neutral 用于纯信息标注（班级/题型/计数），彩色只留给状态语义
  neutral: "bg-secondary text-secondary-foreground",
  mint: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  amber: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
  sky: "bg-sky-400/10 text-sky-600 dark:text-sky-400",
  violet: "bg-primary/10 text-primary",
  pink: "bg-pink-400/10 text-pink-600 dark:text-pink-400",
  red: "bg-red-500/10 text-red-600 dark:text-red-400",
  indigo: "bg-primary/10 text-primary",
}

export function Tag({
  variant = "indigo",
  children,
  className,
}: {
  variant?: TagVariant
  children: React.ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 font-medium text-xs",
        VARIANT_CLASSES[variant],
        className,
      )}
    >
      {children}
    </span>
  )
}
