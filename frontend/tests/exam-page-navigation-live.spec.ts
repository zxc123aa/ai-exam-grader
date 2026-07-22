import { expect, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

test("multiple source files behave as consecutive pages of one exam", async ({
  page,
}) => {
  const apiBase = "http://localhost:8000/api/v1"
  const login = await page.request.post(`${apiBase}/login/access-token`, {
    form: {
      username: process.env.LIVE_TEST_EMAIL ?? "",
      password: process.env.LIVE_TEST_PASSWORD ?? "",
    },
  })
  expect(login.ok()).toBeTruthy()
  const { access_token: token } = await login.json()
  const headers = { Authorization: `Bearer ${token}` }
  const examsResponse = await page.request.get(`${apiBase}/exams/`, { headers })
  const exam = (await examsResponse.json()).data.find(
    (item: { title: string }) => item.title === "高一年级物理期中检测题",
  )
  expect(exam).toBeTruthy()

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
  await page.evaluate(
    (value) => localStorage.setItem("access_token", value),
    token,
  )
  await page.goto(`/exams/${exam.id}/marking`)

  await expect(page.getByText("1.jpg", { exact: true })).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByText(/整张试卷第 1 页，共 2 页/)).toBeVisible()
  await expect(page.getByRole("button", { name: "上一页" })).toBeDisabled()
  await page.getByRole("button", { name: "下一页" }).click()
  await expect(page.getByText("2.jpg", { exact: true })).toBeVisible()
  await expect(page.getByText(/整张试卷第 2 页，共 2 页/)).toBeVisible()
  await expect(page.getByRole("button", { name: "下一页" })).toBeDisabled()
  await page.getByRole("button", { name: "上一页" }).click()
  await expect(page.getByText("1.jpg", { exact: true })).toBeVisible()

  await page.getByRole("button", { name: "试卷页面" }).click()
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByText("2 个源文件，共 2 页")).toBeVisible()
  await expect(dialog.getByText("1.jpg", { exact: true })).toBeVisible()
  await expect(dialog.getByText("2.jpg", { exact: true })).toBeVisible()
  await expect(
    dialog.getByRole("button", { name: "向前移动" }).first(),
  ).toBeDisabled()
  await expect(
    dialog.getByRole("button", { name: "向后移动" }).first(),
  ).toBeEnabled()
})
