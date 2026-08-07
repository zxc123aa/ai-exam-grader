import { expect, type Page, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

const ORG_ID = "30000000-0000-4000-8000-000000000001"

async function mockOpenedSchool(page: Page) {
  await page.route("**/api/v1/users/signup/verify", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "signup-access-token",
        token_type: "bearer",
        organization: {
          id: ORG_ID,
          code: "DF-7K3M9Q",
          name: "启明实验学校",
          organization_type: "school",
        },
        trial_ends_at: "2026-08-27T08:00:00Z",
        answer_quota: 200,
      }),
    })
  })
  await page.route("**/api/v1/users/me", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: "40000000-0000-4000-8000-000000000001",
        email: "owner@qiming.example",
        full_name: "周老师",
        is_active: true,
        is_superuser: false,
        role: "school_owner",
        org_id: ORG_ID,
        org_name: "启明实验学校",
      }),
    })
  })
  await page.route("**/api/v1/org/settings", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        name: "启明实验学校",
        code: "DF-7K3M9Q",
        organization_type: "school",
        exam_sharing_enabled: false,
        contact_name: "周老师",
      }),
    })
  })
  await page.route("**/api/v1/org/onboarding", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        class_count: 2,
        teacher_count: 4,
        student_count: 86,
        teacher_exam_count: 0,
      }),
    })
  })
  await page.route("**/api/v1/exams/**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ data: [], count: 0 }),
    })
  })
}

test("登录页可进入学校注册并提交验证邮件", async ({ page }) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))
  await page.route("**/api/v1/users/signup", async (route) => {
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({
        message: "验证邮件已发送，请在 30 分钟内完成验证",
        expires_in_seconds: 1800,
      }),
    })
  })

  await page.goto("/login")
  await page.getByRole("link", { name: "注册学校" }).click()
  await expect(page).toHaveURL(/\/signup$/)
  await expect(
    page.getByRole("heading", { name: "开通学校账号" }),
  ).toBeVisible()
  await expect(page.getByText("200 份")).toBeVisible()
  await page.screenshot({
    path: "/tmp/dianfan-public-signup-desktop.png",
    fullPage: true,
  })

  await page.getByLabel("负责人姓名").fill("周老师")
  await page.getByLabel("学校或机构名称").fill("启明实验学校")
  await page.getByLabel("负责人邮箱").fill("owner@qiming.example")
  await page.getByLabel("登录密码").fill("Dianfan-Test-2026")
  await page.getByLabel("确认密码").fill("Dianfan-Test-2026")
  await page.getByRole("button", { name: "验证邮箱并开通" }).click()

  const sent = page.getByTestId("signup-email-sent")
  await expect(
    sent.getByRole("heading", { name: "查收验证邮件" }),
  ).toBeVisible()
  await expect(sent.getByText("owner@qiming.example")).toBeVisible()
  expect(errors).toEqual([])
})

test("邮箱验证后自动登录并展示真实开通进度", async ({ page }) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))
  await mockOpenedSchool(page)
  await page.setViewportSize({ width: 390, height: 844 })

  await page.goto(`/signup/verify?token=${"a".repeat(43)}`)
  await expect(page).toHaveURL(/\/getting-started$/)
  const setup = page.getByTestId("getting-started-page")
  await expect(setup.getByRole("heading", { name: "学校已开通" })).toBeVisible()
  await expect(setup.getByText("启明实验学校")).toBeVisible()
  await expect(setup.getByText("DF-7K3M9Q")).toBeVisible()
  await expect(setup.getByText("2 个班级")).toBeVisible()
  await expect(setup.getByText("4 位老师")).toBeVisible()
  await expect(setup.getByText("86 名学生")).toBeVisible()
  await expect(
    setup.getByRole("button", { name: "用老师账号登录" }),
  ).toBeEnabled()

  const hasHorizontalOverflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth >
      document.documentElement.clientWidth,
  )
  expect(hasHorizontalOverflow).toBe(false)
  await page.screenshot({
    path: "/tmp/dianfan-public-signup-mobile.png",
    fullPage: true,
  })
  expect(errors).toEqual([])
})
