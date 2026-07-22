import path from "node:path"

import { expect, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

test("reference GUI keeps every recognized answer while flagging uncertain OCR", async ({
  page,
}) => {
  test.setTimeout(240_000)

  const sourceImage = path.resolve(
    process.cwd(),
    "../参考算法/2_试卷分析文件/material/2.jpg",
  )
  const screenshot = path.resolve(
    process.cwd(),
    "../outputs/reference-gui-full-flow.png",
  )

  await page.goto("http://127.0.0.1:3417")
  await expect(page.locator("#health span")).toContainText("8 路并发")

  await page.locator("#file-input").setInputFiles(sourceImage)
  await expect(page.locator("#phase")).toContainText("1 张图片待分析")

  const layoutResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/api/layout") && response.ok(),
  )
  await page.locator("#analyze").click()
  const layoutPayload = await (await layoutResponsePromise).json()
  const layoutQuestionNumbers = layoutPayload.layouts.flatMap(
    (layout: { regions?: Array<{ questionNumber?: string }> }) =>
      (layout.regions ?? []).map((region) => region.questionNumber),
  )
  expect(layoutQuestionNumbers.length).toBeGreaterThan(0)
  await expect(page.locator("#layout-summary")).toContainText(
    `${layoutQuestionNumbers.length} 个题目块`,
  )

  const recognitionResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/api/recognize") && response.ok(),
  )
  await page.locator("#recognize").click()
  const recognitionPayload = await (await recognitionResponsePromise).json()
  const results = recognitionPayload.results as Array<{
    questionNumber?: string
    studentAnswer?: string
    confidence?: number
  }>

  expect(recognitionPayload.concurrency).toBe(8)
  expect(results).toHaveLength(layoutQuestionNumbers.length)
  expect(results.map((item) => item.questionNumber)).toEqual(
    layoutQuestionNumbers,
  )
  expect(
    results.every((item) => (item.studentAnswer ?? "").trim().length > 0),
  ).toBeTruthy()
  expect(
    results.every(
      (item) =>
        typeof item.confidence === "number" &&
        item.confidence >= 0 &&
        item.confidence <= 1,
    ),
  ).toBeTruthy()

  await expect(page.locator("#results .result-row")).toHaveCount(results.length)
  await expect(page.locator("#phase")).toContainText("8 路")
  await page.screenshot({ path: screenshot, fullPage: true })
})
