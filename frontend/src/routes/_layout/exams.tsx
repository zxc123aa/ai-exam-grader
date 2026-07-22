import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Search } from "lucide-react"
import { Suspense } from "react"

import { ExamsService } from "@/client"
import { DataTable } from "@/components/Common/DataTable"
import AddExam from "@/components/Exams/AddExam"
import { columns } from "@/components/Exams/columns"
import PendingExams from "@/components/Pending/PendingExams"

function getExamsQueryOptions() {
  return {
    queryFn: () => ExamsService.readExams({ skip: 0, limit: 100 }),
    queryKey: ["exams"],
  }
}

export const Route = createFileRoute("/_layout/exams")({
  component: Exams,
  head: () => ({
    meta: [
      {
        title: "考试管理 - 智阅卷",
      },
    ],
  }),
})

function ExamsTableContent() {
  const { data: exams } = useSuspenseQuery(getExamsQueryOptions())

  if (exams.data.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-dashed bg-card/50 py-16 text-center">
        <div className="rounded-full bg-muted p-4 mb-4">
          <Search className="h-8 w-8 text-muted-foreground" />
        </div>
        <h3 className="text-lg font-semibold">还没有考试</h3>
        <p className="text-muted-foreground">
          创建第一场考试，然后导入卷子图片或 PDF
        </p>
        <div className="mt-4">
          <AddExam />
        </div>
      </div>
    )
  }

  return <DataTable columns={columns} data={exams.data} />
}

function ExamsTable() {
  return (
    <Suspense fallback={<PendingExams />}>
      <ExamsTableContent />
    </Suspense>
  )
}

function Exams() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">考试管理</h1>
          <p className="text-muted-foreground">
            创建考试，导入一份卷子图片/PDF，然后识别题目内容和准备标准答案
          </p>
        </div>
        <AddExam />
      </div>
      <ExamsTable />
    </div>
  )
}
