import { useQuery } from "@tanstack/react-query"
import type { ColumnDef } from "@tanstack/react-table"

import { type UserPublic, UsersService } from "@/client"
import { Tag } from "@/components/Common/Tag"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { ROLE_LABELS, ROLE_TAG_VARIANTS, resolveRole } from "./roleMeta"
import { UserActionsMenu } from "./UserActionsMenu"

export type UserTableData = UserPublic & {
  isCurrentUser: boolean
}

/** 「任教」列：仅教师/学校管理员有任教班级，其他角色显示占位符。 */
function TeachingClassesCell({ user }: { user: UserTableData }) {
  const role = resolveRole(user)
  const hasTeachingProfile = role === "teacher" || role === "school_admin"
  const { data } = useQuery({
    queryKey: ["teaching-profile", user.id],
    queryFn: () => UsersService.readTeachingProfile({ userId: user.id }),
    enabled: hasTeachingProfile,
  })

  const classNames = data?.class_names ?? []
  if (!hasTeachingProfile || classNames.length === 0) {
    return <span className="text-muted-foreground text-sm">—</span>
  }
  return (
    <div className="flex flex-wrap items-center gap-1">
      {classNames.map((name) => (
        <Tag key={name} variant="neutral">
          {name}
        </Tag>
      ))}
    </div>
  )
}

export const columns: ColumnDef<UserTableData>[] = [
  {
    accessorKey: "full_name",
    header: "姓名",
    cell: ({ row }) => {
      const fullName = row.original.full_name
      return (
        <div className="flex items-center gap-2">
          <span
            className={cn("font-medium", !fullName && "text-muted-foreground")}
          >
            {fullName || "未填写"}
          </span>
          {row.original.isCurrentUser && (
            <Badge variant="outline" className="text-xs">
              You
            </Badge>
          )}
        </div>
      )
    },
  },
  {
    accessorKey: "email",
    header: "邮箱",
    cell: ({ row }) => (
      <span className="text-muted-foreground">{row.original.email}</span>
    ),
  },
  {
    accessorKey: "employee_no",
    header: "工号",
    cell: ({ row }) => (
      <span className="text-muted-foreground text-sm">
        {row.original.employee_no || "—"}
      </span>
    ),
  },
  {
    accessorKey: "org_name",
    header: "学校",
    cell: ({ row }) => (
      <span className="text-muted-foreground text-sm">
        {row.original.org_name ?? "—"}
      </span>
    ),
  },
  {
    id: "role",
    header: "角色",
    cell: ({ row }) => {
      const role = resolveRole(row.original)
      return <Tag variant={ROLE_TAG_VARIANTS[role]}>{ROLE_LABELS[role]}</Tag>
    },
  },
  {
    id: "teaching",
    header: "任教",
    cell: ({ row }) => <TeachingClassesCell user={row.original} />,
  },
  {
    accessorKey: "is_active",
    header: "状态",
    cell: ({ row }) => (
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "size-2 rounded-full",
            row.original.is_active ? "bg-green-500" : "bg-gray-400",
          )}
        />
        <span className={row.original.is_active ? "" : "text-muted-foreground"}>
          {row.original.is_active ? "已启用" : "已停用"}
        </span>
      </div>
    ),
  },
  {
    id: "actions",
    header: () => <span className="sr-only">操作</span>,
    cell: ({ row }) => (
      <div className="flex justify-end">
        <UserActionsMenu user={row.original} />
      </div>
    ),
  },
]
