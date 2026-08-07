import { expect, type Page, test } from "@playwright/test"

const DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"
const SECOND_ORG_ID = "fa245664-776a-47ac-8dbf-3e2a08bf3708"

const directoryRows = [
  {
    record_type: "student",
    record_id: "10000000-0000-0000-0000-000000000001",
    user_id: "30000000-0000-0000-0000-000000000001",
    student_id: "10000000-0000-0000-0000-000000000001",
    name: "张晨",
    role: "student",
    email: "zhangchen@example.com",
    person_no: "A-001",
    org_id: DEFAULT_ORG_ID,
    org_name: "默认学校",
    class_id: "40000000-0000-0000-0000-000000000001",
    class_name: "001班",
    class_names: ["001班"],
    link_status: "bound",
    is_active: true,
    created_at: "2026-07-27T08:00:00Z",
  },
  {
    record_type: "student",
    record_id: "20000000-0000-0000-0000-000000000002",
    user_id: null,
    student_id: "20000000-0000-0000-0000-000000000002",
    name: "张晨",
    role: "student",
    email: null,
    person_no: "B-009",
    org_id: SECOND_ORG_ID,
    org_name: "示范二中",
    class_id: "40000000-0000-0000-0000-000000000002",
    class_name: "高二 3 班",
    class_names: ["高二 3 班"],
    link_status: "no_account",
    is_active: null,
    created_at: "2026-07-27T08:00:00Z",
  },
]

async function mockDirectory(page: Page) {
  await page.route("**/api/v1/platform/directory**", async (route) => {
    const url = new URL(route.request().url())
    const orgId = url.searchParams.get("org_id")
    const category = url.searchParams.get("category")
    const q = url.searchParams.get("q")?.trim()
    const rows = directoryRows.filter((item) => {
      if (orgId && item.org_id !== orgId) return false
      if (category === "unlinked" && item.link_status === "bound") return false
      if (
        q &&
        !`${item.name} ${item.email} ${item.person_no} ${item.org_name} ${item.class_name}`.includes(
          q,
        )
      ) {
        return false
      }
      return true
    })
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ data: rows, count: rows.length }),
    })
  })
}

test("跨学校搜索能区分同名学生", async ({ page }) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))
  await mockDirectory(page)

  await page.goto("/platform")
  const directory = page.getByTestId("platform-directory-search")
  await directory.getByLabel("搜索人员").fill("张晨")
  await expect(page).toHaveURL(/q=%E5%BC%A0%E6%99%A8/)

  const matches = directory.getByRole("row").filter({ hasText: "张晨" })
  await expect(matches).toHaveCount(2)
  await expect(matches.nth(0)).toContainText("默认学校 · 001班")
  await expect(matches.nth(0)).toContainText("A-001")
  await expect(matches.nth(0)).toContainText("已绑定账号")
  await expect(matches.nth(1)).toContainText("示范二中 · 高二 3 班")
  await expect(matches.nth(1)).toContainText("B-009")
  await expect(matches.nth(1)).toContainText("未开通账号")
  expect(errors).toEqual([])
})

test("学校详情汇总全部人员且窄屏无横向溢出", async ({ page }) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))
  await mockDirectory(page)
  await page.setViewportSize({ width: 390, height: 844 })

  await page.goto(`/platform/${DEFAULT_ORG_ID}`)
  const directory = page.getByTestId("platform-org-directory")
  await expect(directory).toBeVisible()
  await expect(
    directory.getByRole("heading", { name: "账号与学生" }),
  ).toBeVisible()
  await expect(
    directory.getByText("张晨", { exact: true }).last(),
  ).toBeVisible()
  await directory.getByRole("button", { name: "需关联" }).click()
  await expect(directory.getByText("没有需要关联的人员")).toBeVisible()

  const hasHorizontalOverflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth >
      document.documentElement.clientWidth,
  )
  expect(hasHorizontalOverflow).toBe(false)
  expect(errors).toEqual([])
})
