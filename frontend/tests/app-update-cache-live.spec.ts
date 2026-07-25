import { expect, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

test("app update clears CacheStorage without deleting the login token", async ({
  page,
}) => {
  const login = await page.request.post(
    "http://localhost:8000/api/v1/login/access-token",
    {
      form: {
        username: process.env.LIVE_TEST_EMAIL ?? "",
        password: process.env.LIVE_TEST_PASSWORD ?? "",
      },
    },
  )
  expect(login.ok()).toBeTruthy()
  const { access_token: token } = await login.json()

  await page.goto("/login").catch(() => undefined)
  await expect
    .poll(async () => {
      try {
        return await page.evaluate(
          () => performance.getEntriesByType("navigation")[0]?.type,
        )
      } catch {
        return null
      }
    })
    .toBe("reload")
  await page.evaluate(async (accessToken) => {
    localStorage.setItem("access_token", accessToken)
    localStorage.setItem("ai-exam-grader:app-version", "outdated-version")
    const staleCache = await caches.open("app-update-cache-test")
    await staleCache.put("/stale-response", new Response("stale"))
  }, token)

  await page.reload().catch(() => undefined)
  await expect
    .poll(
      async () => {
        try {
          return await page.evaluate(async (expectedToken) => {
            const cacheNames = await caches.keys()
            return {
              cacheWasDeleted: !cacheNames.includes("app-update-cache-test"),
              tokenWasPreserved:
                localStorage.getItem("access_token") === expectedToken,
              versionWasUpdated:
                localStorage.getItem("ai-exam-grader:app-version") !==
                "outdated-version",
            }
          }, token)
        } catch {
          return null
        }
      },
      // 并行跑时主线程繁忙，缓存清理可能需要几秒
      { timeout: 20_000 },
    )
    .toEqual({
      cacheWasDeleted: true,
      tokenWasPreserved: true,
      versionWasUpdated: true,
    })
})
