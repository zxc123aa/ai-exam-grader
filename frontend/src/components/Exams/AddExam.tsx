import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { useState } from "react"

import { type ExamCreate, ExamsService } from "@/client"
import { ExamInfoForm } from "@/components/Exams/ExamInfoForm"
import { Button } from "@/components/ui/button"
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

export default function AddExam() {
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const mutation = useMutation({
    mutationFn: (data: ExamCreate) =>
      ExamsService.createExam({ requestBody: data }),
    onSuccess: () => {
      showSuccessToast("考试创建成功")
      setIsOpen(false)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["exams"] })
    },
  })

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button className="bg-gradient-primary text-white hover:opacity-90">
          <Plus />
          新建考试
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>新建考试</DialogTitle>
          <DialogDescription>
            创建考试后导入这套卷子的图片或 PDF，然后识别题目内容并生成标准答案。
          </DialogDescription>
        </DialogHeader>
        <ExamInfoForm
          submitLabel="创建"
          loading={mutation.isPending}
          onSubmit={(payload) => mutation.mutate(payload)}
          showDemoButton={import.meta.env.DEV}
        />
      </DialogContent>
    </Dialog>
  )
}
