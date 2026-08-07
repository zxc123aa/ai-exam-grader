import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation } from "@tanstack/react-query"
import { createFileRoute, Link, redirect } from "@tanstack/react-router"
import { Check, Mail, ShieldCheck } from "lucide-react"
import { useEffect, useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { type ApiError, UsersService } from "@/client"
import { AuthLayout } from "@/components/Common/AuthLayout"
import { CloudflareTurnstile } from "@/components/Common/CloudflareTurnstile"
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
import { PasswordInput } from "@/components/ui/password-input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { isLoggedIn } from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

const signupSchema = z
  .object({
    organization_type: z.enum(["school", "training", "other"]),
    organization_name: z.string().trim().min(2, "请输入完整的学校或机构名称"),
    contact_name: z.string().trim().min(2, "请输入负责人姓名"),
    email: z.email("请输入有效邮箱"),
    password: z.string().min(8, "密码至少需要 8 个字符").max(128),
    confirm_password: z.string(),
  })
  .refine((values) => values.password === values.confirm_password, {
    message: "两次输入的密码不一致",
    path: ["confirm_password"],
  })

type SignupForm = z.infer<typeof signupSchema>

export const Route = createFileRoute("/signup")({
  component: SignUp,
  beforeLoad: async () => {
    if (isLoggedIn()) throw redirect({ to: "/" })
    if (
      import.meta.env.PROD &&
      import.meta.env.VITE_PUBLIC_SIGNUP_ENABLED !== "true"
    ) {
      throw redirect({ to: "/login" })
    }
  },
  head: () => ({ meta: [{ title: "注册学校 - 点凡阅卷" }] }),
})

function TrialBand() {
  return (
    <div className="grid grid-cols-3 divide-x rounded-lg border bg-muted/25 py-3 text-center">
      <div>
        <strong className="block text-sm">学校 ID</strong>
        <span className="text-muted-foreground text-xs">验证后生成</span>
      </div>
      <div>
        <strong className="block text-sm tabular-nums">30 天</strong>
        <span className="text-muted-foreground text-xs">内测期限</span>
      </div>
      <div>
        <strong className="block text-sm tabular-nums">200 份</strong>
        <span className="text-muted-foreground text-xs">答卷额度</span>
      </div>
    </div>
  )
}

function SignUp() {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [turnstileToken, setTurnstileToken] = useState("")
  const [turnstileKey, setTurnstileKey] = useState(0)
  const [submittedEmail, setSubmittedEmail] = useState<string | null>(null)
  const [countdown, setCountdown] = useState(60)
  const form = useForm<SignupForm>({
    resolver: zodResolver(signupSchema),
    defaultValues: {
      organization_type: "school",
      organization_name: "",
      contact_name: "",
      email: "",
      password: "",
      confirm_password: "",
    },
  })

  useEffect(() => {
    if (!submittedEmail || countdown <= 0) return
    const timer = window.setInterval(
      () => setCountdown((value) => Math.max(0, value - 1)),
      1000,
    )
    return () => window.clearInterval(timer)
  }, [submittedEmail, countdown])

  const requestMutation = useMutation({
    mutationFn: (values: SignupForm) =>
      UsersService.registerOrganization({
        requestBody: {
          organization_type: values.organization_type,
          organization_name: values.organization_name.trim(),
          contact_name: values.contact_name.trim(),
          email: values.email.trim().toLowerCase(),
          password: values.password,
          turnstile_token: turnstileToken,
        },
      }),
    onSuccess: (_, values) => {
      setSubmittedEmail(values.email.trim().toLowerCase())
      setCountdown(60)
      setTurnstileToken("")
      setTurnstileKey((value) => value + 1)
    },
    onError: (error: ApiError) => {
      handleError.call(showErrorToast, error)
      setTurnstileToken("")
      setTurnstileKey((value) => value + 1)
    },
  })

  const resendMutation = useMutation({
    mutationFn: () =>
      UsersService.resendOrganizationSignup({
        requestBody: {
          email: submittedEmail ?? "",
          turnstile_token: turnstileToken,
        },
      }),
    onSuccess: () => {
      showSuccessToast("新的验证邮件已发送")
      setCountdown(60)
      setTurnstileToken("")
      setTurnstileKey((value) => value + 1)
    },
    onError: (error: ApiError) => {
      handleError.call(showErrorToast, error)
      setTurnstileToken("")
      setTurnstileKey((value) => value + 1)
    },
  })

  if (submittedEmail) {
    return (
      <AuthLayout>
        <div
          className="flex flex-col gap-6 text-center"
          data-testid="signup-email-sent"
        >
          <span className="mx-auto flex size-12 items-center justify-center rounded-lg border bg-card text-primary">
            <Mail className="size-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold">查收验证邮件</h1>
            <p className="mt-2 text-muted-foreground text-sm leading-6">
              已发送至{" "}
              <strong className="text-foreground">{submittedEmail}</strong>
              <br />
              请在 30 分钟内完成验证。
            </p>
          </div>
          <div className="rounded-lg border bg-muted/25 px-4 py-3 text-left text-muted-foreground text-sm">
            <p className="flex items-start gap-2">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-primary" />
              验证完成后会自动创建学校账号并进入开通引导。
            </p>
          </div>
          <div className="grid gap-3">
            <CloudflareTurnstile
              key={turnstileKey}
              onToken={setTurnstileToken}
              onError={() => showErrorToast("安全验证加载失败，请刷新页面")}
            />
            <LoadingButton
              variant="outline"
              loading={resendMutation.isPending}
              disabled={countdown > 0 || !turnstileToken}
              onClick={() => resendMutation.mutate()}
            >
              {countdown > 0
                ? `${countdown} 秒后可重新发送`
                : "重新发送验证邮件"}
            </LoadingButton>
            <button
              type="button"
              className="text-muted-foreground text-sm hover:text-foreground"
              onClick={() => {
                setSubmittedEmail(null)
                setCountdown(60)
                setTurnstileToken("")
                setTurnstileKey((value) => value + 1)
              }}
            >
              更换邮箱或修改注册信息
            </button>
          </div>
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout contentClassName="max-w-md">
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit((values) =>
            requestMutation.mutate(values),
          )}
          className="flex flex-col gap-5"
          data-testid="organization-signup-form"
        >
          <div className="text-center">
            <h1 className="text-2xl font-bold">开通学校账号</h1>
            <p className="mt-1.5 text-muted-foreground text-sm">
              负责人注册后即可导入老师、学生并开始试批
            </p>
          </div>
          <TrialBand />
          <div className="grid gap-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="organization_type"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>机构类型</FormLabel>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <FormControl>
                        <SelectTrigger data-testid="organization-type-select">
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="school">学校</SelectItem>
                        <SelectItem value="training">培训机构</SelectItem>
                        <SelectItem value="other">其他机构</SelectItem>
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
                    <FormLabel>负责人姓名</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="例如：王老师"
                        autoComplete="name"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
            <FormField
              control={form.control}
              name="organization_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>学校或机构名称</FormLabel>
                  <FormControl>
                    <Input placeholder="请输入完整名称" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>负责人邮箱</FormLabel>
                  <FormControl>
                    <Input
                      type="email"
                      autoComplete="email"
                      placeholder="name@school.edu.cn"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="password"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>登录密码</FormLabel>
                    <FormControl>
                      <PasswordInput autoComplete="new-password" {...field} />
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
                    <FormLabel>确认密码</FormLabel>
                    <FormControl>
                      <PasswordInput autoComplete="new-password" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
          </div>
          <div className="grid gap-3 border-t pt-4">
            <CloudflareTurnstile
              key={turnstileKey}
              onToken={setTurnstileToken}
              onError={() => showErrorToast("安全验证加载失败，请刷新页面")}
            />
            <LoadingButton
              type="submit"
              size="lg"
              loading={requestMutation.isPending}
              disabled={!turnstileToken}
            >
              <Check />
              验证邮箱并开通
            </LoadingButton>
          </div>
          <p className="text-center text-muted-foreground text-sm">
            已有账号？{" "}
            <Link
              to="/login"
              className="font-medium text-primary hover:underline"
            >
              返回登录
            </Link>
          </p>
        </form>
      </Form>
    </AuthLayout>
  )
}

export default SignUp
