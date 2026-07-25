import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { UsersService, type UserUpdateMe } from "@/client"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
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
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { cn } from "@/lib/utils"
import { handleError } from "@/utils"

const formSchema = z.object({
  full_name: z.string().max(30).optional(),
  email: z.email({ message: "邮箱地址格式不正确" }),
})

type FormData = z.infer<typeof formSchema>

/** 基本信息卡：查看态为定义列表，点「编辑」切换为输入框 + 保存/取消。 */
const BasicInfoCard = () => {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [editMode, setEditMode] = useState(false)
  const { user: currentUser } = useAuth()

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      full_name: currentUser?.full_name ?? undefined,
      email: currentUser?.email,
    },
  })

  const toggleEditMode = () => {
    setEditMode(!editMode)
  }

  const mutation = useMutation({
    mutationFn: (data: UserUpdateMe) =>
      UsersService.updateUserMe({ requestBody: data }),
    onSuccess: () => {
      showSuccessToast("个人资料更新成功")
      toggleEditMode()
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries()
    },
  })

  const onSubmit = (data: FormData) => {
    const updateData: UserUpdateMe = {}

    // only include fields that have changed
    if (data.full_name !== currentUser?.full_name) {
      updateData.full_name = data.full_name
    }
    if (data.email !== currentUser?.email) {
      updateData.email = data.email
    }

    mutation.mutate(updateData)
  }

  const onCancel = () => {
    form.reset()
    toggleEditMode()
  }

  return (
    <Card className="gap-0 rounded-2xl py-0 shadow-card">
      <div className="flex items-center justify-between border-b px-5 py-3">
        <h3 className="font-semibold text-sm">基本信息</h3>
        {!editMode && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={toggleEditMode}
          >
            编辑
          </Button>
        )}
      </div>
      <div className="p-5">
        <Form {...form}>
          <form
            onSubmit={form.handleSubmit(onSubmit)}
            className="flex flex-col gap-4"
          >
            <FormField
              control={form.control}
              name="full_name"
              render={({ field }) =>
                editMode ? (
                  <FormItem>
                    <FormLabel className="text-muted-foreground text-xs">
                      姓名
                    </FormLabel>
                    <FormControl>
                      <Input type="text" className="max-w-sm" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                ) : (
                  <FormItem className="gap-1">
                    <FormLabel className="text-muted-foreground text-xs">
                      姓名
                    </FormLabel>
                    <p
                      className={cn(
                        "truncate text-sm",
                        !field.value && "text-muted-foreground",
                      )}
                    >
                      {field.value || "未填写"}
                    </p>
                  </FormItem>
                )
              }
            />

            <FormField
              control={form.control}
              name="email"
              render={({ field }) =>
                editMode ? (
                  <FormItem>
                    <FormLabel className="text-muted-foreground text-xs">
                      邮箱
                    </FormLabel>
                    <FormControl>
                      <Input type="email" className="max-w-sm" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                ) : (
                  <FormItem className="gap-1">
                    <FormLabel className="text-muted-foreground text-xs">
                      邮箱
                    </FormLabel>
                    <p className="truncate text-sm">{field.value}</p>
                  </FormItem>
                )
              }
            />

            {editMode && (
              <div className="flex gap-3">
                <LoadingButton
                  type="submit"
                  loading={mutation.isPending}
                  disabled={!form.formState.isDirty}
                >
                  保存
                </LoadingButton>
                <Button
                  type="button"
                  variant="outline"
                  onClick={onCancel}
                  disabled={mutation.isPending}
                >
                  取消
                </Button>
              </div>
            )}
          </form>
        </Form>
      </div>
    </Card>
  )
}

export default BasicInfoCard
