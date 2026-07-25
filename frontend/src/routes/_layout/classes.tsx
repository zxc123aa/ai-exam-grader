import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useEffect, useState } from "react"

import { ClassesService } from "@/client"
import AddClass from "@/components/Classes/AddClass"
import ClassList from "@/components/Classes/ClassList"
import StudentList from "@/components/Classes/StudentList"
import { PageHead } from "@/components/Common/PageHead"
import { Skeleton } from "@/components/ui/skeleton"

export const Route = createFileRoute("/_layout/classes")({
  component: ClassesPage,
  head: () => ({
    meta: [
      {
        title: "班级学生 - 点凡阅卷",
      },
    ],
  }),
})

function ClassesPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { data, isLoading } = useQuery({
    queryKey: ["classes"],
    queryFn: () => ClassesService.readClasses(),
  })

  const classes = data?.data ?? []

  // 默认选中第一个班级；选中的班级被删除后回退到第一个
  useEffect(() => {
    if (classes.length === 0) {
      if (selectedId !== null) setSelectedId(null)
      return
    }
    if (!selectedId || !classes.some((c) => c.id === selectedId)) {
      setSelectedId(classes[0].id)
    }
  }, [classes, selectedId])

  const selectedClass = classes.find((c) => c.id === selectedId) ?? null

  return (
    <div className="flex flex-col">
      <PageHead
        title="班级学生"
        subtitle="维护班级与学生名单，并绑定学生登录账号"
        actions={<AddClass onCreated={(id) => setSelectedId(id)} />}
      />
      {isLoading ? (
        <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
          <Skeleton className="h-64 w-full rounded-2xl" />
          <Skeleton className="h-64 w-full rounded-2xl" />
        </div>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-[320px_1fr]">
          <ClassList
            classes={classes}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onDeleted={(id) => {
              if (id === selectedId) setSelectedId(null)
            }}
          />
          <StudentList classGroup={selectedClass} />
        </div>
      )}
    </div>
  )
}
