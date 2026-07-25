import { cn } from "@/lib/utils"

/**
 * 按姓名哈希取柔和渐变底色的姓氏头像（点凡阅卷 原型同款）。
 * 同一姓名颜色稳定，不依赖后端头像字段。
 */
const AVATAR_COLORS: Array<[string, string]> = [
  ["#2E5BFF", "#5B7FFF"],
  ["#10B981", "#34D399"],
  ["#F59E0B", "#FB923C"],
  ["#38BDF8", "#2E5BFF"],
  ["#F472B6", "#FB923C"],
  ["#5B7FFF", "#38BDF8"],
]

export function AvatarGradient({
  name,
  size = 36,
  className,
}: {
  name: string
  size?: number
  className?: string
}) {
  const display = (name || "用").trim()
  const index = (display.charCodeAt(0) + display.length) % AVATAR_COLORS.length
  const [c1, c2] = AVATAR_COLORS[index]
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex shrink-0 select-none items-center justify-center rounded-full font-semibold text-white",
        className,
      )}
      style={{
        width: size,
        height: size,
        fontSize: Math.round(size * 0.42),
        background: `linear-gradient(135deg, ${c1}, ${c2})`,
      }}
    >
      {display[0]}
    </span>
  )
}
