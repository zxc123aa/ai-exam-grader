import { useEffect, useRef } from "react"

type TurnstileApi = {
  render: (
    element: HTMLElement,
    options: {
      sitekey: string
      theme: "auto"
      language: string
      callback: (token: string) => void
      "expired-callback": () => void
      "error-callback": () => void
    },
  ) => string
  remove: (widgetId: string) => void
}

declare global {
  interface Window {
    turnstile?: TurnstileApi
  }
}

let scriptPromise: Promise<void> | null = null

function loadTurnstile() {
  if (window.turnstile) return Promise.resolve()
  if (scriptPromise) return scriptPromise
  scriptPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(
      'script[data-dianfan-turnstile="true"]',
    )
    if (existing) {
      existing.addEventListener("load", () => resolve(), { once: true })
      existing.addEventListener("error", () => reject(), { once: true })
      return
    }
    const script = document.createElement("script")
    script.src =
      "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"
    script.async = true
    script.defer = true
    script.dataset.dianfanTurnstile = "true"
    script.onload = () => resolve()
    script.onerror = () => reject(new Error("Turnstile failed to load"))
    document.head.appendChild(script)
  })
  return scriptPromise
}

interface CloudflareTurnstileProps {
  onToken: (token: string) => void
  onError: () => void
}

export function CloudflareTurnstile({
  onToken,
  onError,
}: CloudflareTurnstileProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const tokenCallback = useRef(onToken)
  const errorCallback = useRef(onError)
  tokenCallback.current = onToken
  errorCallback.current = onError

  useEffect(() => {
    const siteKey = import.meta.env.VITE_TURNSTILE_SITE_KEY?.trim()
    if (!siteKey) {
      if (import.meta.env.DEV) {
        tokenCallback.current("local-testing-token")
      } else {
        errorCallback.current()
      }
      return
    }
    let cancelled = false
    let widgetId: string | undefined
    loadTurnstile()
      .then(() => {
        if (cancelled || !containerRef.current || !window.turnstile) return
        widgetId = window.turnstile.render(containerRef.current, {
          sitekey: siteKey,
          theme: "auto",
          language: "zh-cn",
          callback: (token) => tokenCallback.current(token),
          "expired-callback": () => tokenCallback.current(""),
          "error-callback": () => errorCallback.current(),
        })
      })
      .catch(() => errorCallback.current())
    return () => {
      cancelled = true
      if (widgetId && window.turnstile) window.turnstile.remove(widgetId)
    }
  }, [])

  return (
    <div
      ref={containerRef}
      className="min-h-[65px] overflow-hidden"
      data-testid="turnstile-container"
    />
  )
}
