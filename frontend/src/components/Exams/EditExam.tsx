import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { type ExamPublic, ExamsService, type ExamUpdate } from "@/client"
import {
  ExamInfoForm,
  type ExamInfoFormData,
} from "@/components/Exams/ExamInfoForm"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

function toFormDefaults(exam: ExamPublic): Partial<ExamInfoFormData> {
  return {
    title: exam.title,
    subject: exam.subject ?? "",
    grade_level: exam.grade_level ?? "",
    exam_date: exam.exam_date ? exam.exam_date.slice(0, 10) : "",
    description: exam.description ?? "",
    class_ids: exam.class_ids ?? [],
  }
}

export default function EditExam({
  exam,
  trigger,
}: {
  exam: ExamPublic
  trigger?: React.ReactNode
}) {
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const mutation = useMutation({
    mutationFn: (data: ExamUpdate) =>
      ExamsService.updateExam({ examId: exam.id, requestBody: data }),
    onSuccess: () => {
      showSuccessToast("考试信息已更新")
      setIsOpen(false)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["exams"] })
      queryClient.invalidateQueries({ queryKey: ["exam", exam.id] })
    },
  })

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      {trigger && <DialogTrigger asChild>{trigger}</DialogTrigger>}
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>编辑考试信息</DialogTitle>
          <DialogDescription>
            修改考试名称、科目、年级、班级、考试时间和备注。
          </DialogDescription>
        </DialogHeader>
        <ExamInfoForm
          key={String(isOpen)}
          defaultValues={toFormDefaults(exam)}
          submitLabel="保存"
          loading={mutation.isPending}
          onSubmit={(payload) => {
            // 编辑不改动考试归属学校，org_id 仅创建时使用
            const { org_id: _orgId, ...update } = payload
            mutation.mutate(update)
          }}
        />
      </DialogContent>
    </Dialog>
  )
}
