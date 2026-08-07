import { redirect } from "@tanstack/react-router"

import { UsersService } from "@/client"
import { resolveRole } from "@/components/Admin/roleMeta"
import type { TagVariant } from "@/components/Common/Tag"

export const ORG_STATUS_LABELS: Record<string, string> = {
  active: "正常",
  read_only: "只读导出期",
  frozen: "已冻结",
  deleting: "等待删除",
}

export const ORG_STATUS_TAG_VARIANTS: Record<string, TagVariant> = {
  active: "mint",
  read_only: "amber",
  frozen: "red",
  deleting: "red",
}

export function formatOrgDate(value?: string | null): string {
  if (!value) return "—"
  return new Date(value).toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  })
}

/** 平台角色可访问，其余回工作台。 */
export async function requirePlatformRole() {
  const user = await UsersService.readUserMe()
  if (!resolveRole(user).startsWith("platform")) {
    throw redirect({ to: "/" })
  }
}

/** 仅平台超管可访问模型与中转等技术设置。 */
export async function requirePlatformSuperuser() {
  const user = await UsersService.readUserMe()
  if (resolveRole(user) !== "platform_superuser") {
    throw redirect({ to: "/" })
  }
}

/** 平台超管与平台管理员可处理商品、订单和售后。 */
export async function requirePlatformFinanceRole() {
  const user = await UsersService.readUserMe()
  if (!["platform_superuser", "platform_admin"].includes(resolveRole(user))) {
    throw redirect({ to: "/" })
  }
}
