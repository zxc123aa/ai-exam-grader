import type { ColumnDef } from "@tanstack/react-table"

import type { PlatformOrgDetail, PlatformOrgUserItem } from "@/client"
import { ROLE_LABELS, ROLE_TAG_VARIANTS } from "@/components/Admin/roleMeta"
import { DataTable } from "@/components/Common/DataTable"
import { EmptyState } from "@/components/Common/EmptyState"
import { Tag } from "@/components/Common/Tag"
import { cn } from "@/lib/utils"
import { AddOrgOwner } from "./AddOrgOwner"

const columns: ColumnDef<PlatformOrgUserItem>[] = [
  {
    accessorKey: "full_name",
    header: "姓名",
    cell: ({ row }) => (
      <span
        className={cn(
          "font-medium",
          !row.original.full_name && "text-muted-foreground",
        )}
      >
        {row.original.full_name || "未填写"}
      </span>
    ),
  },
  {
    accessorKey: "email",
    header: "邮箱",
    cell: ({ row }) => (
      <span className="text-muted-foreground">{row.original.email}</span>
    ),
  },
  {
    accessorKey: "role",
    header: "角色",
    cell: ({ row }) => {
      const role = row.original.role
      return <Tag variant={ROLE_TAG_VARIANTS[role]}>{ROLE_LABELS[role]}</Tag>
    },
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
]

/** 学校账号列表卡：姓名 / 邮箱 / 角色 / 状态，右上角可追加总管理员。 */
export function OrgUsersCard({
  org,
  canAddOwner,
}: {
  org: PlatformOrgDetail
  canAddOwner: boolean
}) {
  const users = org.users ?? []

  return (
    <div className="rounded-2xl border bg-card p-5 shadow-card">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="font-semibold">账号列表</h3>
        {canAddOwner && <AddOrgOwner orgId={org.id} />}
      </div>
      {users.length === 0 ? (
        <EmptyState
          title="还没有账号"
          description="点击右上角「添加总管理员」为学校创建第一个账号"
        />
      ) : (
        <DataTable columns={columns} data={users} />
      )}
    </div>
  )
}
