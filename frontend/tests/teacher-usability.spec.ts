import { expect, type Page, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

const teacherEmail = "demo2.physics@example.com"
const teacherPassword = "Dianfan@2026"
const publicBaseUrl = process.env.DIANFAN_PUBLIC_BASE_URL
const teacherOwnedExamId = "7a1c8e43-88de-45dd-924b-adbc401d939a"

async function loginAsTeacher(page: Page) {
  await page.goto(publicBaseUrl ? `${publicBaseUrl}/login` : "/login")
  await page.getByTestId("email-input").fill(teacherEmail)
  await page.getByTestId("password-input").fill(teacherPassword)
  await page.getByRole("button", { name: "登录" }).click()
  await page.waitForURL((url) => url.pathname === "/")
}

test("教师查看学生账号时不请求管理员用户列表", async ({ page }) => {
  const forbiddenResponses: string[] = []
  page.on("response", (response) => {
    if (response.status() === 403) forbiddenResponses.push(response.url())
  })

  await loginAsTeacher(page)
  await page.goto(publicBaseUrl ? `${publicBaseUrl}/classes` : "/classes")
  await expect(
    page.getByRole("heading", { name: "班级学生" }).last(),
  ).toBeVisible()
  await expect(
    page
      .locator("span:visible")
      .filter({ hasText: /@school\.local/ })
      .first(),
  ).toBeVisible()
  await expect(page.getByText(/^[0-9a-f]{8}-[0-9a-f-]{27}$/)).toHaveCount(0)
  expect(forbiddenResponses).toEqual([])
})

test("考试创建者打开协作批卷时不请求管理员用户列表", async ({ page }) => {
  const forbiddenResponses: string[] = []
  const userDirectoryRequests: string[] = []
  page.on("response", (response) => {
    if (response.status() === 403) forbiddenResponses.push(response.url())
  })
  page.on("request", (request) => {
    const url = new URL(request.url())
    if (url.pathname.endsWith("/users/") || url.pathname.endsWith("/users")) {
      userDirectoryRequests.push(request.url())
    }
  })

  await loginAsTeacher(page)
  const gradingPath = `/exams/${teacherOwnedExamId}/grading`
  await page.goto(
    publicBaseUrl ? `${publicBaseUrl}${gradingPath}` : gradingPath,
  )
  await expect(page.getByText("协作批卷", { exact: true })).toBeVisible()
  await expect(page.getByText("新建批改批次", { exact: true })).toBeVisible()
  expect(userDirectoryRequests).toEqual([])
  expect(forbiddenResponses).toEqual([])
})

test("教师手机端顶栏清晰且页面没有横向溢出", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await loginAsTeacher(page)
  await page.goto(publicBaseUrl ? `${publicBaseUrl}/exams` : "/exams")

  const topbar = page.locator("header").first()
  await expect(topbar).toBeVisible()
  await expect(topbar.getByRole("heading", { name: "考试管理" })).toHaveCount(0)
  await expect(
    page.getByRole("heading", { name: "考试管理" }).last(),
  ).toBeVisible()

  const hasHorizontalOverflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth >
      document.documentElement.clientWidth,
  )
  expect(hasHorizontalOverflow).toBe(false)
})

test("教师手机端班级学生页没有横向溢出", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await loginAsTeacher(page)
  await page.goto(publicBaseUrl ? `${publicBaseUrl}/classes` : "/classes")
  await expect(
    page
      .locator("span:visible")
      .filter({ hasText: /@school\.local/ })
      .first(),
  ).toBeVisible()

  const hasHorizontalOverflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth >
      document.documentElement.clientWidth,
  )
  expect(hasHorizontalOverflow).toBe(false)
})
