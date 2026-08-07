import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Search } from "lucide-react"
import { Suspense } from "react"

import { ExamsService } from "@/client"
import { DataTable } from "@/components/Common/DataTable"
import { EmptyState } from "@/components/Common/EmptyState"
import { PageHead } from "@/components/Common/PageHead"
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
        title: "考试管理 - 点凡阅卷",
      },
    ],
  }),
})

function ExamsTableContent() {
  const { data: exams } = useSuspenseQuery(getExamsQueryOptions())

  if (exams.data.length === 0) {
    return (
      <EmptyState
        icon={Search}
        title="还没有考试"
        description="点击右上角「新建考试」，然后导入卷子图片或 PDF"
        className="bg-card shadow-card"
      />
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
      <PageHead
        title="考试管理"
        subtitle="创建考试，导入一份卷子图片/PDF，然后识别题目内容和准备标准答案"
        actions={<AddExam />}
      />
      <ExamsTable />
    </div>
  )
}
