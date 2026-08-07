import { useMutation, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router"
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react"
import { useEffect, useRef } from "react"
import { z } from "zod"

import { type ApiError, UsersService } from "@/client"
import { AuthLayout } from "@/components/Common/AuthLayout"
import { Button } from "@/components/ui/button"

const searchSchema = z.object({
  token: z.string().min(32).catch(""),
})

export const Route = createFileRoute("/signup_/verify")({
  component: VerifySignup,
  validateSearch: searchSchema,
  head: () => ({ meta: [{ title: "验证学校账号 - 点凡阅卷" }] }),
})

function errorMessage(error: ApiError | null) {
  const detail = (error?.body as { detail?: string } | undefined)?.detail
  return detail ?? "验证未完成，请重新打开邮件中的链接"
}

function VerifySignup() {
  const { token } = Route.useSearch()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const requested = useRef(false)
  const mutation = useMutation({
    mutationFn: () =>
      UsersService.verifyOrganizationSignup({
        requestBody: { token },
      }),
    onSuccess: async (result) => {
      localStorage.setItem("access_token", result.access_token)
      sessionStorage.setItem("dianfan-signup-result", JSON.stringify(result))
      await queryClient.invalidateQueries({ queryKey: ["currentUser"] })
      navigate({ to: "/getting-started", replace: true })
    },
  })

  useEffect(() => {
    if (!token || requested.current) return
    requested.current = true
    mutation.mutate()
  }, [token, mutation.mutate])

  if (!token || mutation.isError) {
    return (
      <AuthLayout>
        <div className="flex flex-col items-center gap-6 text-center">
          <span className="flex size-12 items-center justify-center rounded-lg border bg-card text-destructive">
            <AlertCircle className="size-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold">验证链接不可用</h1>
            <p className="mt-2 text-muted-foreground text-sm leading-6">
              {errorMessage(mutation.error as ApiError | null)}
            </p>
          </div>
          <div className="grid w-full gap-2">
            <Button asChild>
              <Link to="/signup">返回注册页</Link>
            </Button>
            <Button variant="ghost" asChild>
              <Link to="/login">已有账号，直接登录</Link>
            </Button>
          </div>
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout>
      <div
        className="flex flex-col items-center gap-5 text-center"
        data-testid="signup-verifying"
      >
        <span className="relative flex size-12 items-center justify-center rounded-lg border bg-card text-primary">
          <CheckCircle2 className="size-5 opacity-30" />
          <Loader2 className="absolute size-5 animate-spin" />
        </span>
        <div>
          <h1 className="text-2xl font-bold">正在开通学校账号</h1>
          <p className="mt-2 text-muted-foreground text-sm">
            正在生成学校 ID 和试用额度，请稍候
          </p>
        </div>
      </div>
    </AuthLayout>
  )
}
