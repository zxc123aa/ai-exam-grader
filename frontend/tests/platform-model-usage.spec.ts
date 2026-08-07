import { expect, type Page, test } from "@playwright/test"

const ORG_ID = "00000000-0000-0000-0000-000000000001"

const summary = {
  calls: 128,
  succeeded_calls: 124,
  failed_calls: 3,
  missing_usage_calls: 1,
  success_rate: 0.9688,
  input_tokens: 980_000,
  output_tokens: 260_000,
  image_tokens: 110_000,
  reasoning_tokens: 86_000,
  total_tokens: 1_436_000,
  customer_credits: 286.4,
  internal_cost_rmb: 71.82,
  upstream_cost_rmb: 79.4,
  reconciled_internal_cost_rmb: 54.2,
  cost_variance_rmb: 25.2,
  reconciled_calls: 96,
  unreconciled_calls: 32,
  average_latency_ms: 8_420,
  fallback_calls: 7,
}

const usageRows = [
  {
    id: "10000000-0000-0000-0000-000000000001",
    org_id: ORG_ID,
    org_name: "默认学校",
    exam_id: null,
    grading_run_id: null,
    resource_id: "submission-001:q-8",
    workflow_purpose: "subjective_grading",
    purpose_label: "主观题判分",
    requested_provider: "smart-route",
    requested_model: "gpt-5.6-sol",
    actual_provider: "pomoai",
    actual_model: "gpt-5.6-sol",
    channel_id: null,
    channel_name: "PomoAI 综合通道",
    attempt_number: 1,
    attempt_kind: "primary",
    fallback_used: false,
    http_status: 200,
    error_code: null,
    input_tokens: 8_200,
    output_tokens: 1_800,
    image_tokens: 1_200,
    cached_input_tokens: 0,
    reasoning_tokens: 900,
    total_tokens: 12_100,
    latency_ms: 7_600,
    status: "succeeded",
    customer_credits: 2.42,
    internal_cost_rmb: 0.61,
    upstream_cost_rmb: 0.82,
    cost_variance_rmb: 0.21,
    reconciliation_status: "mismatch",
    created_at: "2026-07-27T08:20:00Z",
  },
  {
    id: "10000000-0000-0000-0000-000000000002",
    org_id: "20000000-0000-0000-0000-000000000002",
    org_name: "示范二中",
    exam_id: null,
    grading_run_id: null,
    resource_id: "answer-002:q-15",
    workflow_purpose: "answer_preparation",
    purpose_label: "参考答案解题",
    requested_provider: "smart-route",
    requested_model: "gpt-5.6-sol",
    actual_provider: "relay-b",
    actual_model: "gpt-5.6-terra",
    channel_id: null,
    channel_name: "备用推理通道",
    attempt_number: 2,
    attempt_kind: "fallback",
    fallback_used: true,
    http_status: 502,
    error_code: "upstream_timeout",
    input_tokens: 5_000,
    output_tokens: 0,
    image_tokens: 900,
    cached_input_tokens: 0,
    reasoning_tokens: 0,
    total_tokens: 5_900,
    latency_ms: 30_000,
    status: "failed",
    customer_credits: 0,
    internal_cost_rmb: 0.12,
    upstream_cost_rmb: null,
    cost_variance_rmb: null,
    reconciliation_status: "pending",
    created_at: "2026-07-27T08:10:00Z",
  },
]

async function mockUsage(page: Page) {
  await page.route(
    "**/api/v1/platform/model-usage/overview**",
    async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          days: 30,
          since: "2026-06-27T00:00:00Z",
          summary,
          organizations: [
            {
              key: ORG_ID,
              label: "默认学校",
              org_id: ORG_ID,
              calls: 86,
              failed_calls: 1,
              total_tokens: 970_000,
              customer_credits: 194,
              internal_cost_rmb: 48.2,
              upstream_cost_rmb: 53.4,
              reconciled_calls: 68,
              average_latency_ms: 7_900,
            },
            {
              key: "20000000-0000-0000-0000-000000000002",
              label: "示范二中",
              org_id: "20000000-0000-0000-0000-000000000002",
              calls: 42,
              failed_calls: 2,
              total_tokens: 466_000,
              customer_credits: 92.4,
              internal_cost_rmb: 23.62,
              upstream_cost_rmb: 26,
              reconciled_calls: 28,
              average_latency_ms: 9_500,
            },
          ],
          purposes: [
            {
              key: "subjective_grading",
              label: "主观题判分",
              calls: 90,
              failed_calls: 2,
              total_tokens: 1_020_000,
              customer_credits: 210,
              internal_cost_rmb: 52.3,
              upstream_cost_rmb: 58.1,
              reconciled_calls: 70,
              average_latency_ms: 8_800,
            },
            {
              key: "answer_preparation",
              label: "参考答案解题",
              calls: 38,
              failed_calls: 1,
              total_tokens: 416_000,
              customer_credits: 76.4,
              internal_cost_rmb: 19.52,
              upstream_cost_rmb: 21.3,
              reconciled_calls: 26,
              average_latency_ms: 7_520,
            },
          ],
          models: [
            {
              key: "pomoai:gpt-5.6-sol",
              label: "pomoai / gpt-5.6-sol",
              calls: 112,
              failed_calls: 1,
              total_tokens: 1_300_000,
              customer_credits: 258,
              internal_cost_rmb: 64.5,
              upstream_cost_rmb: 71.2,
              reconciled_calls: 84,
              average_latency_ms: 8_100,
            },
          ],
          daily: [],
        }),
      })
    },
  )
  await page.route("**/api/v1/platform/model-usage?**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ data: usageRows, count: 2 }),
    })
  })
}

test("平台调用总览可按学校下钻并查看成本明细", async ({ page }) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))
  await mockUsage(page)

  await page.goto("/platform/usage?days=30&page=1")
  await expect(
    page
      .getByTestId("platform-usage-page")
      .getByRole("heading", { name: "调用记录" }),
  ).toBeVisible()
  await expect(page.getByText("96.9%")).toBeVisible()
  await expect(page.getByText("¥79.40")).toBeVisible()
  await expect(page.getByText("96 / 128 次")).toBeVisible()
  await expect(page.getByText("费用有差异").first()).toBeVisible()
  await expect(page.getByText("待同步账单").first()).toBeVisible()
  await expect(page.getByText("实付 ¥0.8200").first()).toBeVisible()
  await expect(page.getByText("差额 +¥0.2100").first()).toBeVisible()
  await expect(
    page.getByText("默认学校", { exact: true }).first(),
  ).toBeVisible()
  await expect(page.getByText("PomoAI 综合通道", { exact: true })).toBeVisible()
  await expect(page.getByText("upstream_timeout")).toBeVisible()

  await page.getByRole("button", { name: /默认学校.*86 次/ }).click()
  await expect(page).toHaveURL(new RegExp(`orgId=${ORG_ID}`))
  await page.screenshot({
    path: "/tmp/platform-usage-desktop.png",
    fullPage: true,
  })
  expect(errors).toEqual([])
})

test("学校详情展示调用摘要且窄屏无横向溢出", async ({ page }) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))
  await mockUsage(page)
  await page.setViewportSize({ width: 390, height: 844 })

  await page.goto(`/platform/${ORG_ID}`)
  const section = page.getByTestId("platform-org-model-usage")
  await expect(section).toBeVisible()
  await expect(section.getByText("模型调用")).toBeVisible()
  await expect(section.getByText(/主观题判分 ·/)).toBeVisible()
  await expect(section.getByRole("link", { name: "查看全部" })).toHaveAttribute(
    "href",
    new RegExp(`/platform/usage.*orgId=${ORG_ID}`),
  )
  const hasHorizontalOverflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth >
      document.documentElement.clientWidth,
  )
  expect(hasHorizontalOverflow).toBe(false)
  await page.screenshot({
    path: "/tmp/platform-usage-narrow.png",
    fullPage: true,
  })
  expect(errors).toEqual([])
})
