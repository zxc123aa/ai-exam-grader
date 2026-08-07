import type { UserPublic, UserRole } from "@/client"
import type { TagVariant } from "@/components/Common/Tag"

export const ROLE_LABELS: Record<UserRole, string> = {
  platform_superuser: "平台超管",
  platform_admin: "平台管理员",
  platform_support: "平台运营",
  school_owner: "总管理员",
  school_admin: "管理员",
  teacher: "教师",
  student: "学生",
}

export const ROLE_TAG_VARIANTS: Record<UserRole, TagVariant> = {
  platform_superuser: "violet",
  platform_admin: "indigo",
  platform_support: "sky",
  school_owner: "indigo",
  school_admin: "sky",
  teacher: "mint",
  student: "amber",
}

export const ROLE_OPTIONS: UserRole[] = [
  "platform_superuser",
  "platform_admin",
  "platform_support",
  "school_owner",
  "school_admin",
  "teacher",
  "student",
]

/** 旧角色值到新角色值的临时映射（阶段 1 兼容用，阶段 2 移除）。 */
const LEGACY_ROLE_MAP: Record<string, UserRole> = {
  superuser: "platform_superuser",
  admin: "school_owner",
}

function normalizeRole(role: string | null | undefined): UserRole | null {
  if (!role) return null
  if (role in LEGACY_ROLE_MAP) return LEGACY_ROLE_MAP[role]
  if (role in ROLE_LABELS) return role as UserRole
  return null
}

/** 兼容旧数据：旧枚举值映射为新角色；role 缺失时按 is_superuser 推导。 */
export function resolveRole(
  user: Pick<UserPublic, "role" | "is_superuser">,
): UserRole {
  return (
    normalizeRole(user.role) ??
    (user.is_superuser ? "platform_superuser" : "teacher")
  )
}

/**
 * 当前用户可分配的角色，按角色分级：
 * platform_superuser → 平台管理员/运营；school_owner → school_admin/teacher/student；
 * school_admin → teacher/student；其他角色不能创建/改角色。
 */
export function assignableRoles(
  currentUser: Pick<UserPublic, "role" | "is_superuser"> | null | undefined,
): UserRole[] {
  if (!currentUser) return []
  switch (resolveRole(currentUser)) {
    case "platform_superuser":
      return ["platform_admin", "platform_support"]
    case "platform_admin":
      return []
    case "school_owner":
      return ["school_admin", "teacher", "student"]
    case "school_admin":
      return ["teacher", "student"]
    default:
      return []
  }
}
