import { test as setup } from "@playwright/test"
import {
  firstSuperuser,
  firstSuperuserPassword,
  schoolOwnerEmail,
  schoolOwnerPassword,
} from "./config.ts"

const authFile = "playwright/.auth/user.json"
const schoolAuthFile = "playwright/.auth/school.json"

setup("authenticate", async ({ page }) => {
  await page.goto("/login")
  await page.getByTestId("email-input").fill(firstSuperuser)
  await page.getByTestId("password-input").fill(firstSuperuserPassword)
  await page.getByRole("button", { name: /登录|Log In/ }).click()
  await page.waitForURL((url) => ["/", "/platform"].includes(url.pathname))
  await page.context().storageState({ path: authFile })
})

// 学校业务页（/exams 等）的默认登录态：平台超管会被重定向到 /platform，
// 这些页面必须用学校账号（默认学校 school_owner）。
setup("authenticate as school owner", async ({ page }) => {
  await page.goto("/login")
  await page.getByTestId("email-input").fill(schoolOwnerEmail)
  await page.getByTestId("password-input").fill(schoolOwnerPassword)
  await page.getByRole("button", { name: /登录|Log In/ }).click()
  await page.waitForURL((url) => url.pathname === "/")
  await page.context().storageState({ path: schoolAuthFile })
})
