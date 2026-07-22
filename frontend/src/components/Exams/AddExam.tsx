import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Dices, Plus } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { type ExamCreate, ExamsService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

const formSchema = z.object({
  title: z.string().min(1, { message: "请输入考试名称" }).max(255),
  subject: z.string().max(100).optional(),
  grade_level: z.string().max(100).optional(),
})

type FormData = z.infer<typeof formSchema>

function emptyToNull(value?: string) {
  const trimmed = value?.trim()
  return trimmed ? trimmed : null
}

export default function AddExam() {
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    defaultValues: {
      title: "",
      subject: "",
      grade_level: "",
    },
  })

  const mutation = useMutation({
    mutationFn: (data: ExamCreate) =>
      ExamsService.createExam({ requestBody: data }),
    onSuccess: () => {
      showSuccessToast("考试创建成功")
      form.reset()
      setIsOpen(false)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["exams"] })
    },
  })

  const onSubmit = (data: FormData) => {
    mutation.mutate({
      title: data.title.trim(),
      subject: emptyToNull(data.subject),
      grade_level: emptyToNull(data.grade_level),
    })
  }

  const fillRandomDemo = () => {
    const subjects = ["物理", "数学", "语文", "英语", "化学"]
    const grades = ["七年级", "八年级", "九年级", "高一年级"]
    const titles = [
      "期中检测题",
      "阶段性质量检测",
      "单元综合测试",
      "期末模拟卷",
    ]
    const subject = subjects[Math.floor(Math.random() * subjects.length)]
    const grade = grades[Math.floor(Math.random() * grades.length)]
    const title = `${grade}${subject}${titles[Math.floor(Math.random() * titles.length)]}`
    form.setValue("title", title, { shouldValidate: true })
    form.setValue("subject", subject)
    form.setValue("grade_level", grade)
  }

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button>
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
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)}>
            <div className="grid gap-4 py-4">
              <FormField
                control={form.control}
                name="title"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      考试名称 <span className="text-destructive">*</span>
                    </FormLabel>
                    <FormControl>
                      <Input placeholder="八年级期中考试" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="subject"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>科目</FormLabel>
                    <FormControl>
                      <Input placeholder="语文" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="grade_level"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>年级</FormLabel>
                    <FormControl>
                      <Input placeholder="八年级" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline" disabled={mutation.isPending}>
                  取消
                </Button>
              </DialogClose>
              <LoadingButton type="submit" loading={mutation.isPending}>
                创建
              </LoadingButton>
              {import.meta.env.DEV && (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={fillRandomDemo}
                  disabled={mutation.isPending}
                >
                  <Dices />
                  随机演示信息
                </Button>
              )}
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
