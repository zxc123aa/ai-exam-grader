import { Link } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"

const ErrorComponent = () => {
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

      <p className="text-lg text-muted-foreground mb-4 text-center z-10">
        系统暂时无法完成请求，请稍后重试。
      </p>
      <Link to="/">
        <Button>返回首页</Button>
      </Link>
    </div>
  )
}

export default ErrorComponent
