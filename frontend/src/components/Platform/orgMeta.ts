import { redirect } from "@tanstack/react-router"

import { UsersService } from "@/client"
import { resolveRole } from "@/components/Admin/roleMeta"
import type { TagVariant } from "@/components/Common/Tag"

export const ORG_STATUS_LABELS: Record<string, string> = {
  active: "正常",
  suspended: "已停用",
}

export const ORG_STATUS_TAG_VARIANTS: Record<string, TagVariant> = {
  active: "mint",
  suspended: "red",
}

export function formatOrgDate(value?: string | null): string {
  if (!value) return "—"
  return new Date(value).toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  })
}

/** 仅平台角色（platform_superuser / platform_support）可访问，其余回工作台。 */
export async function requirePlatformRole() {
  const user = await UsersService.readUserMe()
  if (!resolveRole(user).startsWith("platform")) {
    throw redirect({ to: "/" })
  }
}

/** 仅平台超管可访问（系统设置等写敏感页），其余回工作台。 */
export async function requirePlatformSuperuser() {
  const user = await UsersService.readUserMe()
  if (resolveRole(user) !== "platform_superuser") {
    throw redirect({ to: "/" })
  }
}
