import {
  createFileRoute,
  Link as RouterLink,
  redirect,
} from "@tanstack/react-router"
import { UserRoundX } from "lucide-react"

import { AuthLayout } from "@/components/Common/AuthLayout"
import { Button } from "@/components/ui/button"
import { isLoggedIn } from "@/hooks/useAuth"

export const Route = createFileRoute("/signup")({
  component: SignUp,
  beforeLoad: async () => {
    if (isLoggedIn()) {
      throw redirect({
        to: "/",
      })
    }
  },
  head: () => ({
    meta: [
      {
        title: "注册 - 点凡阅卷",
      },
    ],
  }),
})

function SignUp() {
  return (
    <AuthLayout>
      <div className="flex flex-col items-center gap-6 text-center">
        <div className="flex size-12 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
          <UserRoundX className="size-6" />
        </div>
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl font-bold">公开注册已关闭</h1>
          <p className="text-sm text-muted-foreground">
            点凡阅卷 以学校为单位开通使用，账号由学校管理员统一创建。
            请联系你所在学校的管理员获取账号。
          </p>
        </div>
        <RouterLink to="/login">
          <Button variant="outline">返回登录</Button>
        </RouterLink>
      </div>
    </AuthLayout>
  )
}

export default SignUp
