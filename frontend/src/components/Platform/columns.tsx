import { Link } from "@tanstack/react-router"
import type { ColumnDef } from "@tanstack/react-table"
import { ArrowRight } from "lucide-react"

import type { PlatformOrgListItem } from "@/client"
import { Tag } from "@/components/Common/Tag"
import { Button } from "@/components/ui/button"
import { ORG_STATUS_LABELS, ORG_STATUS_TAG_VARIANTS } from "./orgMeta"

export const columns: ColumnDef<PlatformOrgListItem>[] = [
  {
    accessorKey: "name",
    header: "学校名称",
    cell: ({ row }) => (
      <div className="grid gap-0.5">
        <span className="font-medium">{row.original.name}</span>
        <span className="font-mono text-muted-foreground text-xs">
          {row.original.code}
        </span>
      </div>
    ),
  },
  {
    id: "owner",
    header: "负责人",
    cell: ({ row }) => {
      const owner = row.original
      const displayName =
        owner.owner_name ||
        owner.contact_name ||
        owner.owner_email?.split("@")[0]
      return (
        <div className="grid max-w-56 gap-0.5">
          <span className="text-sm">{displayName || "尚未创建总管理员"}</span>
          {owner.owner_email && (
            <span className="truncate text-muted-foreground text-xs">
              {owner.owner_email}
            </span>
          )}
        </div>
      )
    },
  },
  {
    id: "people",
    header: "学校人员",
    cell: ({ row }) => (
      <div className="grid gap-0.5 text-sm tabular-nums">
        <span>
          {row.original.teacher_count ?? 0} 位老师 ·{" "}
          {row.original.student_count ?? 0} 名学生
        </span>
        <span className="text-muted-foreground text-xs">
          {row.original.class_count ?? 0} 个班级
        </span>
      </div>
    ),
  },
  {
    id: "accounts",
    header: "账号",
    cell: ({ row }) => (
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-sm tabular-nums">
          {row.original.account_count ?? 0} 个
        </span>
        {(row.original.unbound_student_count ?? 0) > 0 && (
          <Tag variant="amber">
            {row.original.unbound_student_count} 名学生未开通
          </Tag>
        )}
      </div>
    ),
  },
  {
    accessorKey: "exam_count",
    header: "考试",
    cell: ({ row }) => (
      <span className="text-muted-foreground text-sm tabular-nums">
        {row.original.exam_count ?? 0} 场
      </span>
    ),
  },
  {
    accessorKey: "status",
    header: "状态",
    cell: ({ row }) => {
      const status = row.original.status
      return (
        <Tag variant={ORG_STATUS_TAG_VARIANTS[status] ?? "indigo"}>
          {ORG_STATUS_LABELS[status] ?? status}
        </Tag>
      )
    },
  },
  {
    id: "actions",
    header: () => <span className="sr-only">操作</span>,
    cell: ({ row }) => (
      <div className="flex justify-end">
        <Button variant="ghost" size="sm" asChild>
          <Link
            to="/platform/$orgId"
            params={{ orgId: row.original.id }}
            data-testid={`org-detail-link-${row.original.code}`}
          >
            进入详情
            <ArrowRight />
          </Link>
        </Button>
      </div>
    ),
  },
]
