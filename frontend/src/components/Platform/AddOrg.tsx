import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { type PlatformOrgCreate, PlatformService } from "@/client"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
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

const formSchema = z
  .object({
    name: z.string().min(1, { message: "请输入学校名称" }),
    code: z
      .string()
      .min(1, { message: "请输入学校代码" })
      .regex(/^[a-z0-9][a-z0-9-]*$/, {
        message: "代码只能包含小写字母、数字和连字符",
      }),
    contact_name: z.string().optional(),
    with_owner: z.boolean(),
    owner_email: z.string().optional(),
    owner_full_name: z.string().optional(),
    owner_password: z.string().optional(),
  })
  .superRefine((data, ctx) => {
    if (!data.with_owner) return
    if (!data.owner_email || !z.email().safeParse(data.owner_email).success) {
      ctx.addIssue({
        code: "custom",
        message: "请输入有效的邮箱地址",
        path: ["owner_email"],
      })
    }
    if (!data.owner_password || data.owner_password.length < 8) {
      ctx.addIssue({
        code: "custom",
        message: "密码至少 8 位",
        path: ["owner_password"],
      })
    }
  })

type FormData = z.infer<typeof formSchema>

/** 新建学校向导：学校信息 + 可选的首个总管理员账号（同一事务创建）。 */
const AddOrg = () => {
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      name: "",
      code: "",
      contact_name: "",
      with_owner: true,
      owner_email: "",
      owner_full_name: "",
      owner_password: "",
    },
  })

  const withOwner = form.watch("with_owner")

  const mutation = useMutation({
    mutationFn: (data: PlatformOrgCreate) =>
      PlatformService.createOrg({ requestBody: data }),
    onSuccess: () => {
      showSuccessToast("学校创建成功")
      form.reset()
      setIsOpen(false)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-orgs"] })
    },
  })

  const onSubmit = (data: FormData) => {
    mutation.mutate({
      name: data.name,
      code: data.code,
      contact_name: data.contact_name || null,
      owner: data.with_owner
        ? {
            email: data.owner_email ?? "",
            full_name: data.owner_full_name || null,
            password: data.owner_password ?? "",
          }
        : null,
    })
  }

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button data-testid="add-org-button">
          <Plus className="mr-2" />
          新建学校
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>新建学校</DialogTitle>
          <DialogDescription>
            创建学校租户，可同时创建首个总管理员账号。
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)}>
            <div className="grid gap-4 py-4">
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      学校名称 <span className="text-destructive">*</span>
                    </FormLabel>
                    <FormControl>
                      <Input
                        placeholder="例如：示范二中"
                        data-testid="add-org-name"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="code"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      学校代码 <span className="text-destructive">*</span>
                    </FormLabel>
                    <FormControl>
                      <Input
                        placeholder="例如：demo2"
                        data-testid="add-org-code"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="contact_name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>联系人</FormLabel>
                    <FormControl>
                      <Input placeholder="请输入联系人姓名" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="with_owner"
                render={({ field }) => (
                  <FormItem className="flex items-center gap-3 space-y-0">
                    <FormControl>
                      <Checkbox
                        checked={field.value}
                        onCheckedChange={field.onChange}
                        data-testid="add-org-with-owner"
                      />
                    </FormControl>
                    <FormLabel className="font-normal">
                      同时创建总管理员账号
                    </FormLabel>
                  </FormItem>
                )}
              />

              {withOwner && (
                <div className="grid gap-4 rounded-xl border bg-muted/30 p-4">
                  <FormField
                    control={form.control}
                    name="owner_email"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>
                          总管理员邮箱{" "}
                          <span className="text-destructive">*</span>
                        </FormLabel>
                        <FormControl>
                          <Input
                            placeholder="请输入邮箱"
                            type="email"
                            data-testid="add-org-owner-email"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="owner_full_name"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>总管理员姓名</FormLabel>
                        <FormControl>
                          <Input placeholder="请输入姓名" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="owner_password"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>
                          初始密码 <span className="text-destructive">*</span>
                        </FormLabel>
                        <FormControl>
                          <Input
                            placeholder="至少 8 位"
                            type="password"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
              )}
            </div>

            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline" disabled={mutation.isPending}>
                  取消
                </Button>
              </DialogClose>
              <LoadingButton
                type="submit"
                loading={mutation.isPending}
                data-testid="add-org-submit"
              >
                创建
              </LoadingButton>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

export default AddOrg
