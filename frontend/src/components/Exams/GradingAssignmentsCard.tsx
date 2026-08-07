import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"

import { ExamsService, type GradingAssigneePublic } from "@/client"
import { resolveRole } from "@/components/Admin/roleMeta"
import { Tag } from "@/components/Common/Tag"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

export function useGradingAssignments(examId: string, enabled = true) {
  return useQuery({
    queryKey: ["grading-assignments", examId],
    queryFn: () => ExamsService.readGradingAssignments({ examId }),
    enabled,
  })
}

/**
 * 协作批卷分配卡片：共享批卷开关 + 班级×老师分配矩阵。
 * 仅考试 owner 或学校管理角色（school_owner/school_admin）可见；
 * 被分配的普通老师不显示（他们只看到 workbench 的范围条）。
 */
export function GradingAssignmentsCard({ examId }: { examId: string }) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const examQuery = useQuery({
    queryKey: ["exam", examId],
    queryFn: () => ExamsService.readExam({ examId }),
  })
  // 仅考试 owner 或管理角色拉取分配数据（避免普通老师 403）
  const canManage = Boolean(
    user &&
      (examQuery.data?.owner_id === user.id ||
        ["school_owner", "school_admin"].includes(resolveRole(user))),
  )
  const assignmentsQuery = useGradingAssignments(examId, canManage)

  // 编辑草稿：null 表示尚未从服务端数据初始化
  const [draftEnabled, setDraftEnabled] = useState<boolean | null>(null)
  const [draftMap, setDraftMap] = useState<Record<string, string> | null>(null)

  const data = assignmentsQuery.data
  useEffect(() => {
    if (!data || draftMap !== null) return
    setDraftEnabled(data.enabled)
    setDraftMap(
      Object.fromEntries(
        (data.assignments ?? []).map((item) => [item.class_id, item.user_id]),
      ),
    )
  }, [data, draftMap])

  const teachers = data?.candidates ?? []

  const save = useMutation({
    mutationFn: () =>
      ExamsService.updateGradingAssignments({
        examId,
        requestBody: {
          enabled: draftEnabled ?? false,
          assignments: Object.entries(draftMap ?? {})
            .filter(([, userId]) => Boolean(userId))
            .map(([class_id, user_id]) => ({ class_id, user_id })),
        },
      }),
    onSuccess: () => showSuccessToast("批卷分配已保存"),
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["grading-assignments", examId],
      })
      queryClient.invalidateQueries({ queryKey: ["exam", examId] })
      queryClient.invalidateQueries({ queryKey: ["exams"] })
    },
  })

  if (!user || !examQuery.data || !canManage) return null

  // 班级列表 = 已分配 + 未分配（有答卷的班）
  const classes = [
    ...(data?.assignments ?? []).map((item) => ({
      class_id: item.class_id,
      class_name: item.class_name,
    })),
    ...(data?.unassigned ?? []),
  ]
  const enabled = draftEnabled ?? data?.enabled ?? false
  const unassignedCount = classes.filter(
    (item) => !draftMap?.[item.class_id],
  ).length

  const teacherLabel = (teacher: GradingAssigneePublic) => teacher.user_name
  const sortedTeachers = (classId: string) =>
    [...teachers].sort((a, b) => {
      const aTeaches = a.class_ids?.includes(classId) ? 0 : 1
      const bTeaches = b.class_ids?.includes(classId) ? 0 : 1
      return aTeaches - bTeaches
    })

  return (
    <Card className="rounded-2xl shadow-card">
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle className="font-medium text-sm">协作批卷</CardTitle>
        {enabled && unassignedCount > 0 && (
          <Tag variant="amber">还有 {unassignedCount} 个班未分配老师</Tag>
        )}
      </CardHeader>
      <CardContent className="grid gap-4">
        <label
          className="flex items-center gap-2 text-sm"
          htmlFor="shared-grading-enabled"
        >
          <Checkbox
            id="shared-grading-enabled"
            checked={enabled}
            onCheckedChange={(checked) => setDraftEnabled(checked === true)}
          />
          开启共享批卷
          <span className="text-muted-foreground text-xs">
            多位老师按班级分工批改同一场考试
          </span>
        </label>
        {enabled && (
          <div className="grid gap-2">
            {classes.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                还没有班级答卷，先在导入中心上传学生答卷后再分配
              </p>
            ) : (
              classes.map((item) => (
                <div
                  key={item.class_id}
                  className="flex items-center justify-between gap-3 border-b pb-2 last:border-0 last:pb-0"
                >
                  <span className="text-sm">{item.class_name}</span>
                  <select
                    className="h-9 rounded-md border bg-background px-3 text-sm"
                    value={draftMap?.[item.class_id] ?? ""}
                    onChange={(event) =>
                      setDraftMap({
                        ...(draftMap ?? {}),
                        [item.class_id]: event.target.value,
                      })
                    }
                  >
                    <option value="">未分配</option>
                    {sortedTeachers(item.class_id).map((teacher) => (
                      <option key={teacher.user_id} value={teacher.user_id}>
                        {teacherLabel(teacher)}
                        {teacher.class_ids?.includes(item.class_id)
                          ? "（任教）"
                          : ""}
                      </option>
                    ))}
                  </select>
                </div>
              ))
            )}
          </div>
        )}
        <div className="flex justify-end">
          <Button
            className="bg-gradient-primary text-white hover:opacity-90"
            onClick={() => save.mutate()}
            disabled={save.isPending || draftMap === null}
          >
            保存分配
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
