import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query"
import { createRouter, RouterProvider } from "@tanstack/react-router"
import { StrictMode } from "react"
import ReactDOM from "react-dom/client"
import { ApiError, OpenAPI } from "./client"
import { ThemeProvider } from "./components/theme-provider"
import { Toaster } from "./components/ui/sonner"
import { useAppUpdateCache } from "./hooks/useAppUpdateCache"
import "./index.css"
import { routeTree } from "./routeTree.gen"

OpenAPI.BASE = import.meta.env.VITE_API_URL
OpenAPI.TOKEN = async () => {
  return localStorage.getItem("access_token") || ""
}

const handleApiError = (error: Error) => {
  if (!(error instanceof ApiError)) return
  // 401 = 凭证失效（token 过期/用户被删），一律登出；
  // 403 只在「凭证无法校验」时登出——角色权限不足（403 业务响应）不能踢登录，
  // 否则教师访问 admin 专属接口会被误踢到登录页。
  const isAuthFailure =
    error.status === 401 ||
    (error.status === 403 &&
      (error.body as { detail?: string } | undefined)?.detail ===
        "Could not validate credentials")
  if (isAuthFailure) {
    localStorage.removeItem("access_token")
    window.location.href = "/login"
  }
}
const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: handleApiError,
  }),
  mutationCache: new MutationCache({
    onError: handleApiError,
  }),
})

const router = createRouter({ routeTree })
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
}

const AppUpdateCacheGuard = () => {
  useAppUpdateCache()
  return null
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppUpdateCacheGuard />
    <ThemeProvider defaultTheme="dark" storageKey="vite-ui-theme">
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
        <Toaster richColors closeButton />
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
