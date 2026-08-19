import { Link, useRouter } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"

/** 全局错误边界：至少把真实原因露出来（ muted 小字），别再只给一句套话。 */
const ErrorComponent = ({ error }: { error?: unknown }) => {
  const router = useRouter()
  const message =
    error instanceof Error
      ? error.message
      : typeof error === "string"
        ? error
        : ""
  if (error) console.error("[页面错误]", error)
  return (
    <div
      className="flex min-h-screen items-center justify-center flex-col p-4"
      data-testid="error-component"
    >
      <div className="flex items-center z-10">
        <div className="flex flex-col ml-4 items-center justify-center p-4">
          <span className="text-6xl md:text-8xl font-bold leading-none mb-4">
            错误
          </span>
          <span className="text-2xl font-bold mb-2">出现错误</span>
        </div>
      </div>

      <p className="text-lg text-muted-foreground mb-2 text-center z-10">
        系统暂时无法完成请求，请稍后重试。
      </p>
      {message && (
        <p className="mb-2 max-w-lg break-all text-center text-muted-foreground/70 text-xs">
          {message}
        </p>
      )}
      <div className="z-10 mt-2 flex gap-2">
        <Button variant="outline" onClick={() => router.invalidate()}>
          重试
        </Button>
        <Link to="/">
          <Button>返回首页</Button>
        </Link>
      </div>
    </div>
  )
}

export default ErrorComponent
