import { expect, test } from "@playwright/test"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"
import { createUser } from "./utils/privateApi"
import { randomEmail, randomPassword } from "./utils/random"
import { logInUser } from "./utils/user"

test("Admin page is accessible and shows correct title", async ({ page }) => {
  await page.goto("/admin")
  await expect(
    page.getByRole("heading", { name: "平台账号" }).last(),
  ).toBeVisible()
  await expect(page.getByText("维护点凡平台内部管理员与运营账号")).toBeVisible()
  await expect(page.getByRole("link", { name: "学校账号" })).toHaveAttribute(
    "href",
    "/platform",
  )
})

test("Add User button is visible", async ({ page }) => {
  await page.goto("/admin")
  await expect(page.getByRole("button", { name: "添加用户" })).toBeVisible()
})

test("平台账号页与学校人员目录职责分离", async ({ page }) => {
  await page.goto("/admin")

  await expect(page.getByText("示范二中")).toHaveCount(0)
  await expect(page.getByText("当前账号", { exact: true })).toBeVisible()
  await expect(page.getByText("未填写", { exact: true })).toHaveCount(0)
  await expect(page.getByText("You", { exact: true })).toHaveCount(0)
  await expect(page.getByRole("button", { name: "批量导入" })).toHaveCount(0)
})

test.describe("Admin user management", () => {
  test("Create a new user successfully", async ({ page }) => {
    await page.goto("/admin")

    const email = randomEmail()
    const password = randomPassword()
    const fullName = "Test User Admin"

    await page.getByRole("button", { name: "添加用户" }).click()

    await page.getByPlaceholder("请输入邮箱").fill(email)
    await page.getByPlaceholder("请输入姓名").fill(fullName)
    await page.getByPlaceholder("请输入密码").fill(password)
    await page.getByPlaceholder("请再次输入密码").fill(password)

    await page.getByRole("button", { name: "保存" }).click()

    await expect(page.getByText("用户创建成功")).toBeVisible()

    await expect(page.getByRole("dialog")).not.toBeVisible()

    const userRow = page.getByRole("row").filter({ hasText: email })
    await expect(userRow).toBeVisible()
  })

  test("Create a platform support account", async ({ page }) => {
    await page.goto("/admin")

    const email = randomEmail()
    const password = randomPassword()

    await page.getByRole("button", { name: "添加用户" }).click()

    await page.getByPlaceholder("请输入邮箱").fill(email)
    await page.getByPlaceholder("请输入密码").fill(password)
    await page.getByPlaceholder("请再次输入密码").fill(password)

    const dialog = page.getByRole("dialog")
    await dialog.getByRole("combobox").click()
    await page.getByRole("option", { name: "平台运营" }).click()

    await dialog.getByRole("button", { name: "保存" }).click()

    await expect(page.getByText("用户创建成功")).toBeVisible()

    await expect(page.getByRole("dialog")).not.toBeVisible()

    const userRow = page.getByRole("row").filter({ hasText: email })
    await expect(userRow.getByText("平台运营")).toBeVisible()
  })

  test("Edit a user successfully", async ({ page }) => {
    await page.goto("/admin")

    const email = randomEmail()
    const password = randomPassword()
    const originalName = "Original Name"
    const updatedName = "Updated Name"

    await page.getByRole("button", { name: "添加用户" }).click()
    await page.getByPlaceholder("请输入邮箱").fill(email)
    await page.getByPlaceholder("请输入姓名").fill(originalName)
    await page.getByPlaceholder("请输入密码").fill(password)
    await page.getByPlaceholder("请再次输入密码").fill(password)
    await page.getByRole("button", { name: "保存" }).click()

    await expect(page.getByText("用户创建成功")).toBeVisible()
    await expect(page.getByRole("dialog")).not.toBeVisible()

    const userRow = page.getByRole("row").filter({ hasText: email })
    await userRow.getByRole("button").click()

    await page.getByRole("menuitem", { name: "编辑用户" }).click()

    await page.getByPlaceholder("请输入姓名").fill(updatedName)
    await page.getByRole("button", { name: "保存" }).click()

    await expect(page.getByText("用户信息更新成功")).toBeVisible()
    await expect(userRow.getByText(updatedName).first()).toBeVisible()
  })

  test("Delete a user successfully", async ({ page }) => {
    await page.goto("/admin")

    const email = randomEmail()
    const password = randomPassword()

    await page.getByRole("button", { name: "添加用户" }).click()
    await page.getByPlaceholder("请输入邮箱").fill(email)
    await page.getByPlaceholder("请输入密码").fill(password)
    await page.getByPlaceholder("请再次输入密码").fill(password)
    await page.getByRole("button", { name: "保存" }).click()

    await expect(page.getByText("用户创建成功")).toBeVisible()

    await expect(page.getByRole("dialog")).not.toBeVisible()

    const userRow = page.getByRole("row").filter({ hasText: email })
    await userRow.getByRole("button").click()

    await page.getByRole("menuitem", { name: "删除用户" }).click()

    await page.getByRole("button", { name: "确认删除" }).click()

    await expect(page.getByText("用户已删除")).toBeVisible()

    await expect(
      page.getByRole("row").filter({ hasText: email }),
    ).not.toBeVisible()
  })

  test("Cancel user creation", async ({ page }) => {
    await page.goto("/admin")

    await page.getByRole("button", { name: "添加用户" }).click()
    await page.getByPlaceholder("请输入邮箱").fill("test@example.com")

    await page.getByRole("button", { name: "取消" }).click()

    await expect(page.getByRole("dialog")).not.toBeVisible()
  })

  test("Email is required and must be valid", async ({ page }) => {
    await page.goto("/admin")

    await page.getByRole("button", { name: "添加用户" }).click()

    await page.getByPlaceholder("请输入邮箱").fill("invalid-email")
    await page.getByPlaceholder("请输入邮箱").blur()

    await expect(page.getByText("Invalid email address")).toBeVisible()
  })

  test("Password must be at least 8 characters", async ({ page }) => {
    await page.goto("/admin")

    await page.getByRole("button", { name: "添加用户" }).click()

    await page.getByPlaceholder("请输入邮箱").fill(randomEmail())
    await page.getByPlaceholder("请输入密码").fill("short")
    await page.getByPlaceholder("请再次输入密码").fill("short")
    await page.getByRole("button", { name: "保存" }).click()

    await expect(
      page.getByText("Password must be at least 8 characters"),
    ).toBeVisible()
  })

  test("Passwords must match", async ({ page }) => {
    await page.goto("/admin")

    await page.getByRole("button", { name: "添加用户" }).click()

    await page.getByPlaceholder("请输入邮箱").fill(randomEmail())
    await page.getByPlaceholder("请输入密码").fill(randomPassword())
    await page.getByPlaceholder("请再次输入密码").fill("different12345")
    await page.getByPlaceholder("请再次输入密码").blur()

    await expect(page.getByText("The passwords don't match")).toBeVisible()
  })
})

test.describe("Admin page access control", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("Non-superuser cannot access admin page", async ({ page }) => {
    const email = randomEmail()
    const password = randomPassword()

    await createUser({ email, password })
    await logInUser(page, email, password)

    await page.goto("/admin")

    await expect(
      page.getByRole("heading", { name: "用户管理" }),
    ).not.toBeVisible()
    await expect(page).not.toHaveURL(/\/admin/)
  })

  test("Superuser can access admin page", async ({ page }) => {
    await logInUser(page, firstSuperuser, firstSuperuserPassword)

    await page.goto("/admin")

    await expect(
      page.getByRole("heading", { name: "平台账号" }).last(),
    ).toBeVisible()
  })
})
