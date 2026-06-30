import { Link } from "@tanstack/react-router"

import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const content =
    variant === "responsive" ? (
      <>
        <span
          className={cn(
            "text-sm font-semibold tracking-normal group-data-[collapsible=icon]:hidden",
            className,
          )}
        >
          AI Exam Grader
        </span>
        <span
          title="AI Exam Grader"
          className={cn(
            "hidden size-7 items-center justify-center rounded-md bg-primary text-primary-foreground text-xs font-semibold group-data-[collapsible=icon]:flex",
            className,
          )}
        >
          A
        </span>
      </>
    ) : (
      <span
        className={cn(
          variant === "full"
            ? "text-sm font-semibold tracking-normal"
            : "flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground text-xs font-semibold",
          className,
        )}
      >
        {variant === "full" ? "AI Exam Grader" : "A"}
      </span>
    )

  if (!asLink) {
    return content
  }

  return <Link to="/">{content}</Link>
}
