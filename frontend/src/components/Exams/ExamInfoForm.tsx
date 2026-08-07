import { zodResolver } from "@hookform/resolvers/zod"
import { useQuery } from "@tanstack/react-query"
import { Dices } from "lucide-react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { ClassesService } from "@/client"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { DialogClose, DialogFooter } from "@/components/ui/dialog"
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

const formSchema = z.object({
  title: z.string().min(1, { message: "请输入考试名称" }).max(255),
  subject: z.string().min(1, { message: "请输入科目" }).max(100),
  grade_level: z.string().min(1, { message: "请输入年级" }).max(100),
  exam_date: z.string().min(1, { message: "请选择考试时间" }),
  description: z.string().max(1000).optional(),
  class_ids: z
    .array(z.string())
    .min(1, { message: "请至少关联一个班级（可先在「班级学生」页创建）" }),
  org_id: z.string().optional(),
})

export type ExamInfoFormData = z.infer<typeof formSchema>

export type ExamInfoPayload = {
  title: string
  subject: string | null
  grade_level: string | null
  exam_date: string | null
  description: string | null
  class_ids: string[]
  org_id: string | null
}

function emptyToNull(value?: string) {
  const trimmed = value?.trim()
  return trimmed ? trimmed : null
}

export function toExamInfoPayload(data: ExamInfoFormData): ExamInfoPayload {
  return {
    title: data.title.trim(),
    subject: emptyToNull(data.subject),
    grade_level: emptyToNull(data.grade_level),
    exam_date: emptyToNull(data.exam_date),
    description: emptyToNull(data.description),
    class_ids: data.class_ids,
    org_id: emptyToNull(data.org_id),
  }
}

export const examInfoEmptyDefaults: ExamInfoFormData = {
  title: "",
  subject: "",
  grade_level: "",
  exam_date: "",
  description: "",
  class_ids: [],
  org_id: "",
}

export function ExamInfoForm({
  defaultValues,
  loading,
  submitLabel,
  onSubmit,
  showDemoButton = false,
}: {
  defaultValues?: Partial<ExamInfoFormData>
  loading?: boolean
  submitLabel: string
  onSubmit: (payload: ExamInfoPayload) => void
  showDemoButton?: boolean
}) {
  const form = useForm<ExamInfoFormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    defaultValues: { ...examInfoEmptyDefaults, ...defaultValues },
  })

  const classGroupsQuery = useQuery({
    queryKey: ["classes"],
    queryFn: () => ClassesService.readClasses(),
  })
  const classGroups = classGroupsQuery.data

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
    form.setValue("exam_date", new Date().toISOString().slice(0, 10))
  }

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit((data) =>
          onSubmit(toExamInfoPayload(data)),
        )}
      >
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
                <FormLabel>
                  科目 <span className="text-destructive">*</span>
                </FormLabel>
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
                <FormLabel>
                  年级 <span className="text-destructive">*</span>
                </FormLabel>
                <FormControl>
                  <Input placeholder="八年级" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="class_ids"
            render={({ field }) => (
              <FormItem>
                <FormLabel>
                  班级 <span className="text-destructive">*</span>
                </FormLabel>
                <div className="grid gap-2 rounded-md border border-input p-3">
                  {classGroupsQuery.isPending ? (
                    <div
                      className="grid gap-2"
                      role="status"
                      aria-label="正在加载班级"
                    >
                      <div className="h-5 w-32 animate-pulse rounded bg-muted" />
                      <div className="h-5 w-40 animate-pulse rounded bg-muted" />
                    </div>
                  ) : classGroupsQuery.isError ? (
                    <p className="text-destructive text-sm">
                      班级加载失败，请稍后重试
                    </p>
                  ) : (classGroups?.data ?? []).length === 0 ? (
                    <p className="text-muted-foreground text-sm">
                      暂无班级，可先在「班级学生」页创建
                    </p>
                  ) : (
                    classGroups?.data.map((group) => (
                      <label
                        key={group.id}
                        htmlFor={`class-${group.id}`}
                        className="flex items-center gap-2 text-sm"
                      >
                        <Checkbox
                          id={`class-${group.id}`}
                          checked={field.value.includes(group.id)}
                          onCheckedChange={(checked) => {
                            field.onChange(
                              checked === true
                                ? [...field.value, group.id]
                                : field.value.filter((id) => id !== group.id),
                            )
                          }}
                        />
                        {group.name}
                        {group.grade_level && (
                          <span className="text-muted-foreground">
                            （{group.grade_level}）
                          </span>
                        )}
                      </label>
                    ))
                  )}
                </div>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="exam_date"
            render={({ field }) => (
              <FormItem>
                <FormLabel>
                  考试时间 <span className="text-destructive">*</span>
                </FormLabel>
                <FormControl>
                  <Input type="date" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="description"
            render={({ field }) => (
              <FormItem>
                <FormLabel>备注</FormLabel>
                <FormControl>
                  <textarea
                    className="border-input min-h-20 w-full rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    placeholder="本次考试范围、注意事项等"
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" disabled={loading}>
              取消
            </Button>
          </DialogClose>
          <LoadingButton type="submit" loading={loading}>
            {submitLabel}
          </LoadingButton>
          {showDemoButton && (
            <Button
              type="button"
              variant="ghost"
              onClick={fillRandomDemo}
              disabled={loading}
            >
              <Dices />
              随机演示信息
            </Button>
          )}
        </DialogFooter>
      </form>
    </Form>
  )
}
