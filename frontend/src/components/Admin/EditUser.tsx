import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Pencil } from "lucide-react"
import { useEffect, useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { ClassesService, type UserPublic, UsersService } from "@/client"
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
} from "@/components/ui/dialog"
import { DropdownMenuItem } from "@/components/ui/dropdown-menu"
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
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"
import { assignableRoles, ROLE_LABELS, resolveRole } from "./roleMeta"

const formSchema = z
  .object({
    email: z.email({ message: "Invalid email address" }),
    full_name: z.string().optional(),
    password: z
      .string()
      .min(8, { message: "Password must be at least 8 characters" })
      .optional()
      .or(z.literal("")),
    confirm_password: z.string().optional(),
    role: z
      .enum([
        "platform_superuser",
        "platform_support",
        "school_owner",
        "school_admin",
        "teacher",
        "student",
      ])
      .optional(),
    is_active: z.boolean().optional(),
    class_ids: z.array(z.string()).optional(),
    subjects: z.string().optional(),
  })
  .refine((data) => !data.password || data.password === data.confirm_password, {
    message: "The passwords don't match",
    path: ["confirm_password"],
  })

type FormData = z.infer<typeof formSchema>

/** 任教信息仅对教师/学校管理员有意义。 */
const TEACHING_ROLES = ["teacher", "school_admin"]

/** 任教科目按中英文逗号拆分，去掉空白项。 */
function parseSubjects(value: string | undefined): string[] {
  return (value ?? "")
    .split(/[,，]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

interface EditUserProps {
  user: UserPublic
  onSuccess: () => void
}

const EditUser = ({ user, onSuccess }: EditUserProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { user: currentUser } = useAuth()
  const userRole = resolveRole(user)
  const roleOptions = assignableRoles(currentUser)
  // 非平台超管不能改动平台超管的角色
  const roleDisabled =
    userRole === "platform_superuser" &&
    !roleOptions.includes("platform_superuser")

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      email: user.email,
      full_name: user.full_name ?? undefined,
      role: userRole,
      is_active: user.is_active,
      class_ids: [],
      subjects: "",
    },
  })

  // 跟随表单里当前选中的角色，切成学生/平台角色时即时隐藏任教字段
  const selectedRole = form.watch("role") ?? userRole
  const showTeachingFields = TEACHING_ROLES.includes(selectedRole)

  const { data: classGroups } = useQuery({
    queryKey: ["classes"],
    queryFn: () => ClassesService.readClasses(),
    enabled: isOpen && showTeachingFields,
  })
  // 平台账号编辑学校老师时，只列目标用户所在学校的班级
  const classes = (classGroups?.data ?? []).filter(
    (c) => !user.org_id || c.org_id === user.org_id,
  )

  const { data: teachingProfile } = useQuery({
    queryKey: ["teaching-profile", user.id],
    queryFn: () => UsersService.readTeachingProfile({ userId: user.id }),
    enabled: isOpen && showTeachingFields,
  })

  // 回显已有任教信息
  useEffect(() => {
    if (!teachingProfile) return
    form.setValue("class_ids", teachingProfile.class_ids ?? [])
    form.setValue("subjects", (teachingProfile.subjects ?? []).join("，"))
  }, [teachingProfile, form])

  const mutation = useMutation({
    mutationFn: async (data: FormData) => {
      // exclude confirm_password from submission data and remove password if empty
      const { confirm_password: _, class_ids, subjects, ...submitData } = data
      if (!submitData.password) {
        delete submitData.password
      }
      await UsersService.updateUser({
        userId: user.id,
        requestBody: submitData,
      })
      if (showTeachingFields) {
        await UsersService.updateTeachingProfile({
          userId: user.id,
          requestBody: {
            class_ids: class_ids ?? [],
            subjects: parseSubjects(subjects),
          },
        })
      }
    },
    onSuccess: () => {
      showSuccessToast("用户信息更新成功")
      setIsOpen(false)
      onSuccess()
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] })
      queryClient.invalidateQueries({ queryKey: ["teaching-profile", user.id] })
    },
  })

  const onSubmit = (data: FormData) => {
    mutation.mutate(data)
  }

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DropdownMenuItem
        onSelect={(e) => e.preventDefault()}
        onClick={() => setIsOpen(true)}
      >
        <Pencil />
        编辑用户
      </DropdownMenuItem>
      <DialogContent className="sm:max-w-md">
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)}>
            <DialogHeader>
              <DialogTitle>编辑用户</DialogTitle>
              <DialogDescription>修改以下用户信息。</DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-4">
              <FormField
                control={form.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      邮箱 <span className="text-destructive">*</span>
                    </FormLabel>
                    <FormControl>
                      <Input
                        placeholder="请输入邮箱"
                        type="email"
                        {...field}
                        required
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="full_name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>姓名</FormLabel>
                    <FormControl>
                      <Input placeholder="请输入姓名" type="text" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="password"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>设置新密码</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="请输入新密码"
                        type="password"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="confirm_password"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>确认新密码</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="请再次输入新密码"
                        type="password"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="role"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>角色</FormLabel>
                    <Select
                      value={field.value}
                      onValueChange={field.onChange}
                      disabled={roleDisabled}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="请选择角色" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {(roleOptions.includes(userRole)
                          ? roleOptions
                          : [userRole, ...roleOptions]
                        ).map((role) => (
                          <SelectItem key={role} value={role}>
                            {ROLE_LABELS[role]}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {showTeachingFields && (
                <>
                  <FormField
                    control={form.control}
                    name="class_ids"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>任教班级</FormLabel>
                        <div className="grid gap-2 rounded-md border p-3">
                          {classes.length === 0 && (
                            <span className="text-muted-foreground text-sm">
                              本校暂无班级
                            </span>
                          )}
                          {classes.map((c) => (
                            <div
                              key={c.id}
                              className="flex items-center gap-2 text-sm"
                            >
                              <Checkbox
                                id={`teaching-class-${c.id}`}
                                checked={field.value?.includes(c.id) ?? false}
                                onCheckedChange={(checked) => {
                                  const current = field.value ?? []
                                  field.onChange(
                                    checked
                                      ? [...current, c.id]
                                      : current.filter((id) => id !== c.id),
                                  )
                                }}
                              />
                              <label
                                htmlFor={`teaching-class-${c.id}`}
                                className="cursor-pointer"
                              >
                                {c.name}
                              </label>
                            </div>
                          ))}
                        </div>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="subjects"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>任教科目</FormLabel>
                        <FormControl>
                          <Input
                            placeholder="多个科目用逗号分隔，如：物理，数学"
                            type="text"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </>
              )}

              <FormField
                control={form.control}
                name="is_active"
                render={({ field }) => (
                  <FormItem className="flex items-center gap-3 space-y-0">
                    <FormControl>
                      <Checkbox
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    </FormControl>
                    <FormLabel className="font-normal">启用账号</FormLabel>
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
                保存
              </LoadingButton>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

export default EditUser
