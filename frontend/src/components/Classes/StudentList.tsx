import { useQuery } from "@tanstack/react-query"
import { UserRound } from "lucide-react"

import { ClassesService, type ClassGroupPublic, UsersService } from "@/client"
import { EmptyState } from "@/components/Common/EmptyState"
import { Tag } from "@/components/Common/Tag"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import AddStudent from "./AddStudent"
import BatchAddStudents from "./BatchAddStudents"
import { StudentActionsMenu } from "./StudentActionsMenu"

interface StudentListProps {
  classGroup: ClassGroupPublic | null
}

/** 右侧学生名单卡：选中班级的学生列表与增删改、绑定账号操作。 */
const StudentList = ({ classGroup }: StudentListProps) => {
  const studentsQuery = useQuery({
    queryKey: ["classes", classGroup?.id, "students"],
    queryFn: () => ClassesService.readStudents({ classId: classGroup!.id }),
    enabled: !!classGroup,
  })

  // 解析绑定账号邮箱：用户列表仅 admin+ 可见，教师端失败时降级显示用户 ID
  const usersQuery = useQuery({
    queryKey: ["student-account-candidates"],
    queryFn: () => UsersService.readUsers({ skip: 0, limit: 100 }),
    retry: false,
  })
  const emailById = new Map(
    (usersQuery.data?.data ?? []).map((user) => [user.id, user.email]),
  )

  if (!classGroup) {
    return (
      <section className="rounded-2xl border bg-card p-4 shadow-card">
        <EmptyState
          icon={UserRound}
          title="未选择班级"
          description="先在左侧选择或新建一个班级。"
        />
      </section>
    )
  }

  const students = studentsQuery.data?.data ?? []

  return (
    <section className="rounded-2xl border bg-card p-4 shadow-card">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold text-sm">
          {classGroup.name} · 学生名单（{students.length} 人）
        </h3>
        <div className="flex items-center gap-2">
          <AddStudent classId={classGroup.id} />
          <BatchAddStudents classId={classGroup.id} />
        </div>
      </div>

      {studentsQuery.isLoading ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : students.length === 0 ? (
        <EmptyState
          icon={UserRound}
          title="暂无学生"
          description="通过「添加学生」或「批量添加」录入学生名单。"
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>姓名</TableHead>
              <TableHead>学号</TableHead>
              <TableHead>绑定账号</TableHead>
              <TableHead>
                <span className="sr-only">操作</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {students.map((student) => (
              <TableRow key={student.id}>
                <TableCell className="font-medium">{student.name}</TableCell>
                <TableCell className="text-muted-foreground">
                  {student.student_no || "—"}
                </TableCell>
                <TableCell>
                  {student.user_id ? (
                    <span className="text-muted-foreground text-sm">
                      {emailById.get(student.user_id) ?? student.user_id}
                    </span>
                  ) : (
                    <Tag variant="amber">未绑定</Tag>
                  )}
                </TableCell>
                <TableCell>
                  <div className="flex justify-end">
                    <StudentActionsMenu student={student} />
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  )
}

export default StudentList
