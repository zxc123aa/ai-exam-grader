import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useForm } from "react-hook-form"
import { z } from "zod"

import {
  type PlatformOrgDetail,
  type PlatformOrgUpdate,
  PlatformService,
} from "@/client"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"
import { ORG_STATUS_LABELS } from "./orgMeta"

const formSchema = z.object({
  name: z.string().min(1, { message: "请输入学校名称" }),
  status: z.enum(["active", "suspended"]),
  contact_name: z.string().optional(),
})

type FormData = z.infer<typeof formSchema>

/** 学校信息卡：仅平台超管可编辑保存，运营角色只读。 */
export function OrgInfoCard({
  org,
  canEdit,
}: {
  org: PlatformOrgDetail
  canEdit: boolean
}) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      name: org.name,
      status: (org.status === "suspended" ? "suspended" : "active") as
        | "active"
        | "suspended",
      contact_name: org.contact_name ?? "",
    },
  })

  const mutation = useMutation({
    mutationFn: (data: PlatformOrgUpdate) =>
      PlatformService.updateOrg({ orgId: org.id, requestBody: data }),
    onSuccess: (updated) => {
      showSuccessToast("学校信息已更新")
      form.reset({
        name: updated.name,
        status: updated.status === "suspended" ? "suspended" : "active",
        contact_name: updated.contact_name ?? "",
      })
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-org", org.id] })
      queryClient.invalidateQueries({ queryKey: ["platform-orgs"] })
    },
  })

  const onSubmit = (data: FormData) => {
    mutation.mutate({
      name: data.name,
      status: data.status,
      contact_name: data.contact_name || null,
    })
  }

  return (
    <div className="rounded-2xl border bg-card p-5 shadow-card">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="font-semibold">学校信息</h3>
        {!canEdit && (
          <span className="text-muted-foreground text-xs">
            仅平台超管可修改
          </span>
        )}
      </div>
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          className="grid gap-4 sm:grid-cols-2"
        >
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>学校名称</FormLabel>
                <FormControl>
                  <Input
                    data-testid="org-info-name"
                    disabled={!canEdit}
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormItem>
            <FormLabel>学校代码</FormLabel>
            <Input value={org.code} disabled />
          </FormItem>

          <FormField
            control={form.control}
            name="status"
            render={({ field }) => (
              <FormItem>
                <FormLabel>状态</FormLabel>
                <Select
                  value={field.value}
                  onValueChange={field.onChange}
                  disabled={!canEdit}
                >
                  <FormControl>
                    <SelectTrigger data-testid="org-info-status">
                      <SelectValue />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    {(["active", "suspended"] as const).map((status) => (
                      <SelectItem key={status} value={status}>
                        {ORG_STATUS_LABELS[status]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
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
                  <Input placeholder="未填写" disabled={!canEdit} {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          {canEdit && (
            <div className="sm:col-span-2">
              <LoadingButton
                type="submit"
                loading={mutation.isPending}
                disabled={!form.formState.isDirty}
                data-testid="org-info-save"
              >
                保存
              </LoadingButton>
            </div>
          )}
        </form>
      </Form>
    </div>
  )
}
