import { Link } from "@tanstack/react-router"
import type { ColumnDef } from "@tanstack/react-table"
import { Copy, Ellipsis, Pencil, Upload } from "lucide-react"

import type { ExamPublic } from "@/client"
import { Tag } from "@/components/Common/Tag"
import EditExam from "@/components/Exams/EditExam"
import { ImportCenterDialog } from "@/components/Exams/ImportCenterDialog"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import { useExamProgress } from "@/hooks/useExamProgress"

function ExamRowActions({ exam }: { exam: ExamPublic }) {
  const { currentStep, allDone } = useExamProgress(exam.id)
  const [, copy] = useCopyToClipboard()

  // 流程未走完 → 进到当前应做步骤；已全部完成 → 直接进批卷工作台
  const target = allDone
    ? ("/exams/$examId/workbench" as const)
    : currentStep.to

  return (
    <div className="flex justify-end gap-2">
      <Button size="sm" asChild>
        <Link to={target} params={{ examId: exam.id }}>
          {allDone ? "进入批卷" : `继续：${currentStep.label}`}
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
          <EditExam
            exam={exam}
            trigger={
              <DropdownMenuItem onSelect={(event) => event.preventDefault()}>
                <Pencil />
                编辑信息
              </DropdownMenuItem>
            }
          />
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

function ExamProgressCell({ examId }: { examId: string }) {
  const { currentStep, allDone, isLoading } = useExamProgress(examId)

  if (isLoading) {
    return <Skeleton className="h-6 w-16 rounded-full" />
  }
  if (allDone) {
    return <Tag variant="mint">已完成</Tag>
  }
  return <Tag variant="amber">{currentStep.label}</Tag>
}

export const columns: ColumnDef<ExamPublic>[] = [
  {
    accessorKey: "title",
    header: "名称",
    cell: ({ row }) => (
      <span className="inline-flex items-center gap-2 font-medium">
        {row.original.title}
        {row.original.shared_grading_enabled && (
          <Tag variant="neutral">协作</Tag>
        )}
      </span>
    ),
  },
  {
    accessorKey: "subject",
    header: "科目",
    cell: ({ row }) => (
      <span className="text-muted-foreground">
        {row.original.subject || "未设置"}
      </span>
    ),
  },
  {
    accessorKey: "grade_level",
    header: "年级",
    cell: ({ row }) => (
      <span className="text-muted-foreground">
        {row.original.grade_level || "未设置"}
      </span>
    ),
  },
  {
    accessorKey: "class_names",
    header: "班级",
    cell: ({ row }) => {
      const names = row.original.class_names ?? []
      if (names.length === 0) {
        return <span className="text-muted-foreground">未关联</span>
      }
      return (
        <div className="flex flex-wrap gap-1">
          {names.map((name) => (
            <Tag key={name} variant="sky">
              {name}
            </Tag>
          ))}
        </div>
      )
    },
  },
  {
    accessorKey: "exam_date",
    header: "考试时间",
    cell: ({ row }) => (
      <span className="text-muted-foreground">
        {row.original.exam_date || "未设置"}
      </span>
    ),
  },
  {
    id: "progress",
    header: "进度",
    cell: ({ row }) => <ExamProgressCell examId={row.original.id} />,
  },
  {
    id: "actions",
    header: "操作",
    cell: ({ row }) => <ExamRowActions exam={row.original} />,
  },
]
