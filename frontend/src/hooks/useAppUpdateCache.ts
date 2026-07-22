import { useEffect } from "react"

const APP_VERSION_STORAGE_KEY = "ai-exam-grader:app-version"

let reloadStarted = false

const clearBrowserCaches = async () => {
  const tasks: Promise<unknown>[] = []

  if ("caches" in window) {
    tasks.push(
      caches
        .keys()
        .then((cacheNames) =>
          Promise.all(cacheNames.map((cacheName) => caches.delete(cacheName))),
        ),
    )
  }

  if ("serviceWorker" in navigator) {
    tasks.push(
      navigator.serviceWorker
        .getRegistrations()
        .then((registrations) =>
          Promise.all(
            registrations.map((registration) => registration.unregister()),
          ),
        ),
    )
  }

  await Promise.allSettled(tasks)
}

const clearCachesAndReload = async () => {
  if (reloadStarted) return

  reloadStarted = true
  await clearBrowserCaches()
  window.location.reload()
}

/**
 * 清理旧版本的浏览器缓存，并在开发期代码更新前执行一次完整刷新。
 *
 * 这里只处理 CacheStorage 和 Service Worker，不会清空 localStorage，
 * 因此 access_token、主题等用户状态都会保留。
 */
export const useAppUpdateCache = () => {
  useEffect(() => {
    const previousVersion = localStorage.getItem(APP_VERSION_STORAGE_KEY)

    if (previousVersion !== __APP_VERSION__) {
      localStorage.setItem(APP_VERSION_STORAGE_KEY, __APP_VERSION__)
      void clearCachesAndReload()
    }

    if (!import.meta.hot) return

    const handleUpdate = () => {
      void clearCachesAndReload()
    }
    const handleFullReload = () => {
      void clearBrowserCaches()
    }

    import.meta.hot.on("vite:afterUpdate", handleUpdate)
    import.meta.hot.on("vite:beforeFullReload", handleFullReload)

    return () => {
      import.meta.hot?.off("vite:afterUpdate", handleUpdate)
      import.meta.hot?.off("vite:beforeFullReload", handleFullReload)
    }
  }, [])
}
