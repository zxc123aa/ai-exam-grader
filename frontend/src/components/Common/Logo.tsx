import { Link } from "@tanstack/react-router"
import { BookOpenCheck } from "lucide-react"

import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

function LogoMark({ className }: { className?: string }) {
  return (
    <span
      title="智阅卷"
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-indigo-700 text-white shadow-sm",
        className,
      )}
    >
      <BookOpenCheck className="size-4.5" strokeWidth={2.2} />
    </span>
  )
}

function LogoWordmark({ className }: { className?: string }) {
  return (
    <span className={cn("flex min-w-0 flex-col leading-tight", className)}>
      <span className="truncate text-sm font-semibold">智阅卷</span>
      <span className="truncate text-[11px] opacity-60">智能阅卷工作台</span>
    </span>
  )
}

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const content =
    variant === "responsive" ? (
      <span className={cn("flex items-center gap-2.5", className)}>
        <LogoMark />
        <span className="group-data-[collapsible=icon]:hidden">
          <LogoWordmark />
        </span>
      </span>
    ) : variant === "full" ? (
      <span className={cn("flex items-center gap-2.5", className)}>
        <LogoMark />
        <LogoWordmark />
      </span>
    ) : (
      <LogoMark className={className} />
    )

  if (!asLink) {
    return content
  }

  return <Link to="/">{content}</Link>
}
