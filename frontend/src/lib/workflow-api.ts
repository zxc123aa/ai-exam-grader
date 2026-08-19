import { OpenAPI } from "@/client"

export async function workflowApi<T>(path: string, options?: RequestInit) {
  const headers = new Headers(options?.headers)
  const token = localStorage.getItem("access_token")
  if (token) headers.set("Authorization", `Bearer ${token}`)
  if (options?.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json")
  }
  const response = await fetch(`${OpenAPI.BASE || ""}/api/v1${path}`, {
    ...options,
    headers,
  })
  if (!response.ok) {
    let message = `请求失败（${response.status}）`
    try {
      const payload = (await response.json()) as { detail?: unknown }
      if (typeof payload.detail === "string") message = payload.detail
    } catch {
      const text = await response.text()
      if (text) message = text
    }
    throw new Error(message)
  }
  // 204/空响应没有 JSON 体，直接 JSON.parse 会抛错（删除类接口就是 204）
  const text = await response.text()
  return (text ? JSON.parse(text) : undefined) as T
}
