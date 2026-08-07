import { expect, test } from "@playwright/test"

test("平台超管可以打开外部调用通道设置", async ({ page }) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))

  await page.goto("/platform/settings")
  await expect(
    page.getByRole("heading", { name: "外部调用通道" }),
  ).toBeVisible()
  await page.getByRole("button", { name: "添加通道" }).click()

  const dialog = page.getByRole("dialog")
  await expect(dialog).toBeVisible()
  await expect(dialog.getByLabel("名称")).toBeVisible()
  await expect(dialog.getByLabel("接口地址")).toBeVisible()
  await expect(dialog.getByLabel("通道并发上限")).toHaveValue("8")
  await expect(dialog.getByRole("button", { name: "保存通道" })).toBeDisabled()
  expect(errors).toEqual([])
})

test("平台超管可以管理地址密钥并读取上游模型", async ({ page }) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))

  await page.goto("/platform/settings")
  await expect(page.getByText("PomoAI 综合通道", { exact: true })).toBeVisible()
  await expect(page.getByText(/https:\/\/www\.pomoai\.ai/)).toBeVisible()
  await expect(page.getByText(/密钥 ····\w{4}/).first()).toBeVisible()
  await expect(
    page.getByText("gpt-5.6-sol", { exact: true }).first(),
  ).toBeVisible()

  const pomoChannelRow = page
    .getByText("PomoAI 综合通道", { exact: true })
    .locator("xpath=ancestor::div[contains(@class, 'grid')][1]")
  await pomoChannelRow.getByRole("button", { name: "管理" }).click()
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByLabel("接口地址")).toHaveValue(
    "https://www.pomoai.ai",
  )
  await expect(dialog.getByLabel("更换调用密钥（留空不变）")).toHaveValue("")
  await expect(dialog.getByText(/完整密钥不会回显/)).toBeVisible()
  await expect(dialog.getByText("gpt-5.6-sol", { exact: true })).toBeVisible()

  await dialog.getByRole("button", { name: "读取上游模型" }).click()
  await expect(dialog.getByText("上游返回的模型")).toBeVisible({
    timeout: 30_000,
  })
  await expect(
    dialog.getByText("claude-haiku-4-5", { exact: true }),
  ).toBeVisible()

  await dialog
    .getByRole("button", { name: "检测", exact: true })
    .first()
    .click()
  await expect(dialog.getByRole("button", { name: "检测中" })).toBeVisible()
  await expect(dialog.getByText(/正常 · \d+\.\d 秒/)).toBeVisible({
    timeout: 30_000,
  })
  expect(errors).toEqual([])
})

test("每个提供者都可以单独保存账单查询密钥", async ({ page }) => {
  const errors: string[] = []
  let channelState: Record<string, unknown> = {}
  page.on("pageerror", (error) => errors.push(error.message))

  await page.route("**/api/v1/platform/provider-channels", async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    body.data = body.data.map((channel: Record<string, unknown>) => {
      if (channel.display_name !== "PomoAI 综合通道") return channel
      channelState = {
        ...channel,
        kind: "official_api",
        billing_credential_configured: false,
        billing_credential_last_four: null,
        billing_user_id: null,
      }
      return channelState
    })
    await route.fulfill({ response, json: body })
  })
  await page.route("**/billing-credential", async (route) => {
    expect(route.request().method()).toBe("PUT")
    expect(route.request().postDataJSON()).toEqual({
      access_token: "provider-billing-secret",
    })
    channelState = {
      ...channelState,
      billing_credential_configured: true,
      billing_credential_last_four: "cret",
    }
    await route.fulfill({ contentType: "application/json", json: channelState })
  })

  await page.goto("/platform/settings")
  const channelRow = page
    .getByText("PomoAI 综合通道", { exact: true })
    .locator("xpath=ancestor::div[contains(@class, 'grid')][1]")
  await channelRow.getByRole("button", { name: "管理" }).click()

  const billing = page
    .getByRole("dialog")
    .getByTestId("channel-billing-reconciliation")
  await expect(billing.getByLabel("账单查询密钥")).toBeVisible()
  await expect(billing.getByLabel("用户 ID")).toHaveCount(0)
  await billing.getByLabel("账单查询密钥").fill("provider-billing-secret")
  await billing.getByRole("button", { name: "保存账单凭据" }).click()
  await expect(billing.getByLabel("账单查询密钥")).toHaveAttribute(
    "placeholder",
    "已配置 ····cret",
  )
  expect(errors).toEqual([])
})

test("New API 通道可同步上游账单并显示认领结果", async ({ page }) => {
  const errors: string[] = []
  let synced = false
  let pomoChannel: Record<string, unknown> = {}
  page.on("pageerror", (error) => errors.push(error.message))

  await page.route("**/api/v1/platform/provider-channels", async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    body.data = body.data.map((channel: Record<string, unknown>) => {
      if (channel.display_name !== "PomoAI 综合通道") return channel
      pomoChannel = {
        ...channel,
        kind: "new_api",
        billing_credential_configured: false,
        billing_credential_last_four: null,
        billing_user_id: null,
      }
      return pomoChannel
    })
    await route.fulfill({ response, json: body })
  })
  await page.route("**/billing-credential", async (route) => {
    expect(route.request().method()).toBe("PUT")
    expect(route.request().postDataJSON()).toEqual({
      access_token: "system-access-token",
      user_id: 42,
    })
    pomoChannel = {
      ...pomoChannel,
      billing_credential_configured: true,
      billing_credential_last_four: "oken",
      billing_user_id: 42,
    }
    await route.fulfill({ contentType: "application/json", json: pomoChannel })
  })
  await page.route("**/reconciliations/sync-new-api", async (route) => {
    synced = true
    const channelId = route.request().url().split("/").at(-3)
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        batch: reconciliationBatch(channelId ?? ""),
        message:
          "读取 1000 条上游记录，对账 1 条，忽略 999 条非本系统或已同步记录",
      }),
    })
  })
  await page.route("**/reconciliations", async (route) => {
    const channelId = route.request().url().split("/").at(-2)
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(
        synced ? [reconciliationBatch(channelId ?? "")] : [],
      ),
    })
  })

  await page.goto("/platform/settings")
  const channelRow = page
    .getByText("PomoAI 综合通道", { exact: true })
    .locator("xpath=ancestor::div[contains(@class, 'grid')][1]")
  await channelRow.getByRole("button", { name: "管理" }).click()

  const dialog = page.getByRole("dialog")
  const billing = dialog.getByTestId("channel-billing-reconciliation")
  await expect(
    billing.getByRole("button", { name: "同步 New API 账单" }),
  ).toBeDisabled()
  await billing
    .getByLabel("账单查询密钥（系统访问令牌）")
    .fill("system-access-token")
  await billing.getByLabel("用户 ID").fill("42")
  await billing.getByRole("button", { name: "保存账单凭据" }).click()
  await expect(
    billing.getByLabel("账单查询密钥（系统访问令牌）"),
  ).toHaveAttribute("placeholder", "已配置 ····oken")
  await expect(
    billing.getByRole("button", { name: "同步 New API 账单" }),
  ).toBeEnabled()
  await billing.getByRole("button", { name: "同步 New API 账单" }).click()
  await expect(billing.getByText("账号累计实付 ¥286.4321")).toBeVisible()
  await expect(billing.getByText("1 条", { exact: true }).first()).toBeVisible()
  await expect(billing.getByText("999 条", { exact: true })).toBeVisible()
  await expect(billing.getByText("PomoAI · d47d4a8b")).toBeVisible()
  expect(errors).toEqual([])
})

function reconciliationBatch(channelId: string) {
  return {
    id: "30000000-0000-4000-8000-000000000001",
    channel_id: channelId,
    source: "new_api",
    period_start: "2026-07-27T08:00:00Z",
    period_end: "2026-07-27T09:00:00Z",
    row_count: 1,
    fetched_count: 1000,
    ignored_count: 999,
    matched_count: 0,
    mismatch_count: 1,
    upstream_system_name: "PomoAI",
    upstream_version: "d47d4a8b",
    upstream_total_granted_quota: 30_000_000,
    upstream_total_used_quota: 19_618_638,
    upstream_total_available_quota: 10_381_362,
    upstream_total_used_rmb: 286.4321,
    quota_per_unit: 500_000,
    usd_exchange_rate: 7.3,
    unlimited_quota: false,
    created_at: "2026-07-27T09:10:00Z",
  }
}

test("功能调度按标准模型配置多个中转通道", async ({ page }) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))

  await page.goto("/platform/routing")
  await expect(
    page
      .getByTestId("platform-routing-page")
      .getByRole("heading", { name: "功能调度", level: 2 }),
  ).toBeVisible()
  await expect(page.getByText("业务功能路由")).toBeVisible()

  const gradingRoute = page.getByTestId("function-route-subjective_grading")
  await expect(gradingRoute.getByText("主观题判分")).toBeVisible()
  await gradingRoute.getByRole("button", { name: /配置|管理/ }).click()

  const dialog = page.getByRole("dialog")
  await expect(
    dialog.getByRole("heading", { name: "主观题判分" }),
  ).toBeVisible()
  await expect(dialog.getByText(/每个模型独立配置主备通道/)).toBeVisible()
  await expect(dialog.getByTestId("routing-model-select")).toBeVisible()
  await expect(dialog.getByTestId("routing-mode-select")).toBeVisible()
  await expect(dialog.getByText("设为平台默认模型")).toBeVisible()
  await expect(dialog.getByTestId("routing-publish")).toBeVisible()
  expect(errors).toEqual([])
})
