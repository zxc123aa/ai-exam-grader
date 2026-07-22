import { Link } from "@tanstack/react-router"
import type { ColumnDef } from "@tanstack/react-table"
import { Copy, Ellipsis, Upload } from "lucide-react"

import type { ExamPublic } from "@/client"
import { ImportCenterDialog } from "@/components/Exams/ImportCenterDialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import { useExamProgress } from "@/hooks/useExamProgress"

const examStatusLabels: Record<string, string> = {
  draft: "草稿",
  marking: "标注中",
  ready: "已就绪",
  processing: "处理中",
  completed: "已完成",
  archived: "已归档",
}

function ExamRowActions({ exam }: { exam: ExamPublic }) {
  const { currentStep } = useExamProgress(exam.id)
  const [, copy] = useCopyToClipboard()

  return (
    <div className="flex justify-end gap-2">
      <Button size="sm" asChild>
        <Link to={currentStep.to} params={{ examId: exam.id }}>
          进入
        </Link>
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm">
            <Ellipsis />
            更多
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <ImportCenterDialog
            exam={exam}
            trigger={
              <DropdownMenuItem onSelect={(event) => event.preventDefault()}>
                <Upload />
                导入中心
              </DropdownMenuItem>
            }
          />
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => copy(exam.id)}>
            <Copy />
            复制考试 ID
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

export const columns: ColumnDef<ExamPublic>[] = [
  {
    accessorKey: "title",
    header: "考试名称",
    cell: ({ row }) => (
      <span className="font-medium">{row.original.title}</span>
    ),
  },
  {
    accessorKey: "subject",
    header: "科目",
    cell: ({ row }) => {
      return (
        <span className="text-muted-foreground">
          {row.original.subject || "未设置"}
        </span>
      )
    },
  },
  {
    accessorKey: "status",
    header: "状态",
    cell: ({ row }) => {
      const status = row.original.status
      return (
        <Badge variant="secondary" className="capitalize">
          {status ? examStatusLabels[status] || status : "未设置"}
        </Badge>
      )
    },
  },
  {
    id: "actions",
    header: "",
    cell: ({ row }) => <ExamRowActions exam={row.original} />,
  },
]
