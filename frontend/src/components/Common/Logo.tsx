import { Link } from "@tanstack/react-router"

import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

function LogoMark({ className }: { className?: string }) {
  return (
    <img
      src="/brand/logo-mark.png"
      alt="点凡阅卷"
      title="点凡阅卷"
      className={cn("size-9 shrink-0 object-contain", className)}
    />
  )
}

function LogoWordmark({ className }: { className?: string }) {
  return (
    <span className={cn("flex min-w-0 flex-col leading-tight", className)}>
      <span className="truncate text-[15px] font-extrabold tracking-wide">
        点凡阅卷
      </span>
      <span className="truncate text-[10px] font-semibold tracking-[1.5px] opacity-50">
        DIANFAN
      </span>
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
