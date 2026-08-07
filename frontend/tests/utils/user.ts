import { expect, type Page } from "@playwright/test"

export async function logInUser(page: Page, email: string, password: string) {
  await page.goto("/login")

  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
  await page.getByRole("button", { name: /登录|Log In/ }).click()
  await page.waitForURL((url) => ["/", "/platform"].includes(url.pathname))
  if (new URL(page.url()).pathname === "/platform") {
    await expect(
      page.getByRole("heading", { name: "学校管理", level: 2 }),
    ).toBeVisible()
  } else {
    await expect(page.getByRole("heading", { name: /老师/ })).toBeVisible()
  }
  await expect(page.getByTestId("user-menu")).toBeVisible()
}

export async function logOutUser(page: Page) {
  await page.getByTestId("user-menu").click()
  await page.getByRole("menuitem", { name: "退出登录" }).click()
  await page.goto("/login")
}
