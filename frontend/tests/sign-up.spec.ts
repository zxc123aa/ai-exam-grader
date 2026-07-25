import { expect, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

test("公开注册已关闭提示可见", async ({ page }) => {
  await page.goto("/signup")

  await expect(
    page.getByRole("heading", { name: "公开注册已关闭" }),
  ).toBeVisible()
  await expect(
    page.getByText("请联系你所在学校的管理员获取账号"),
  ).toBeVisible()
})

test("注册表单不再存在", async ({ page }) => {
  await page.goto("/signup")

  await expect(page.getByTestId("full-name-input")).toHaveCount(0)
  await expect(page.getByTestId("email-input")).toHaveCount(0)
  await expect(page.getByTestId("password-input")).toHaveCount(0)
  await expect(page.getByTestId("confirm-password-input")).toHaveCount(0)
})

test("返回登录按钮跳转到 /login", async ({ page }) => {
  await page.goto("/signup")

  const backLink = page.getByRole("link", { name: "返回登录" })
  await expect(backLink).toBeVisible()
  await backLink.click()

  await expect(page).toHaveURL(/\/login$/)
})
