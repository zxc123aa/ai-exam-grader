import { Link } from "@tanstack/react-router"
import type { ColumnDef } from "@tanstack/react-table"
import { ArrowRight } from "lucide-react"

import type { PlatformOrgListItem } from "@/client"
import { Tag } from "@/components/Common/Tag"
import { Button } from "@/components/ui/button"
import {
  formatOrgDate,
  ORG_STATUS_LABELS,
  ORG_STATUS_TAG_VARIANTS,
} from "./orgMeta"

function CountCell({ value }: { value?: number }) {
  return (
    <span className="tabular-nums text-muted-foreground">{value ?? 0}</span>
  )
}

export const columns: ColumnDef<PlatformOrgListItem>[] = [
  {
    accessorKey: "name",
    header: "学校名称",
    cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
  },
  {
    accessorKey: "code",
    header: "代码",
    cell: ({ row }) => (
      <span className="font-mono text-muted-foreground text-sm">
        {row.original.code}
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
    accessorKey: "exam_count",
    header: "考试数",
    cell: ({ row }) => <CountCell value={row.original.exam_count} />,
  },
  {
    accessorKey: "student_count",
    header: "学生数",
    cell: ({ row }) => <CountCell value={row.original.student_count} />,
  },
  {
    accessorKey: "teacher_count",
    header: "老师数",
    cell: ({ row }) => <CountCell value={row.original.teacher_count} />,
  },
  {
    accessorKey: "created_at",
    header: "创建时间",
    cell: ({ row }) => (
      <span className="text-muted-foreground">
        {formatOrgDate(row.original.created_at)}
      </span>
    ),
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
