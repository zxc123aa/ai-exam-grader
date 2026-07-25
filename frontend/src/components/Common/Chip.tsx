import { cn } from "@/lib/utils"

/**
 * 筛选片（点凡阅卷 原型 chip 同款）。
 * 全圆角小按钮：激活时主色底白字，未激活 secondary 底。
 */
export function Chip({
  active = false,
  children,
  className,
  ...props
}: {
  active?: boolean
  children: React.ReactNode
  className?: string
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      aria-pressed={active}
      className={cn(
        "rounded-full px-3 py-1 font-medium text-xs transition-colors",
        active
          ? "bg-primary text-primary-foreground"
          : "bg-secondary text-secondary-foreground hover:bg-accent",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}
