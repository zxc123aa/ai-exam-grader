import { expect, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

test("new UI renders the reference Node layout response without rewriting it", async ({
  page,
}) => {
  test.setTimeout(180_000)
  const login = await page.request.post(
    "http://localhost:8000/api/v1/login/access-token",
    {
      form: {
        username: process.env.LIVE_TEST_EMAIL ?? "",
        password: process.env.LIVE_TEST_PASSWORD ?? "",
      },
    },
  )
  expect(login.ok()).toBeTruthy()
  const { access_token: token } = await login.json()

  await page.goto("/login").catch(() => undefined)
  await expect
    .poll(async () => {
      try {
        return await page.evaluate(
          () => performance.getEntriesByType("navigation")[0]?.type,
        )
      } catch {
        return null
      }
    })
    .toBe("reload")
  await page.evaluate(
    (value) => localStorage.setItem("access_token", value),
    token,
  )
  const exams = await page.request.get("http://localhost:8000/api/v1/exams/", {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(exams.ok()).toBeTruthy()
  const exam = (await exams.json()).data.find(
    (item: { title: string }) => item.title === "高一年级物理期中检测题",
  )
  expect(exam).toBeTruthy()
  const filesResponse = await page.request.get(
    `http://localhost:8000/api/v1/exams/${exam.id}/files`,
    { headers: { Authorization: `Bearer ${token}` } },
  )
  expect(filesResponse.ok()).toBeTruthy()
  const documents = (await filesResponse.json()).data.filter(
    (item: { document_type: string }) => item.document_type === "blank_exam",
  )
  let targetPageNumber = 1
  for (const document of documents) {
    if (document.stored_file.original_filename === "1.jpg") break
    targetPageNumber += document.page_count ?? 1
  }
  await page.goto(`/exams/${exam.id}/marking`)

  await expect(page.getByRole("button", { name: "试卷页面" })).toBeVisible({
    timeout: 15_000,
  })
  for (let pageNumber = 1; pageNumber < targetPageNumber; pageNumber += 1) {
    await page.getByRole("button", { name: "下一页" }).click()
  }
  await expect(page.getByText("1.jpg", { exact: true })).toBeVisible()
  await expect(
    page.getByText(new RegExp(`整张试卷第 ${targetPageNumber} 页`)),
  ).toBeVisible()
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().includes("/region-candidates") && response.ok(),
  )
  await page.getByRole("button", { name: "检测题目区域" }).click()
  const payload = await (await responsePromise).json()

  expect(payload.engine).toBe("gemini_layout_v1")
  expect(payload.data.length).toBeGreaterThan(0)
  expect(payload.orientation_ms).toBeGreaterThan(0)
  expect(payload.layout_ms).toBeGreaterThan(0)
  expect(payload.refinement_ms).toBeGreaterThanOrEqual(0)
  expect(payload.upright_image).toMatch(/^data:image\//)
  await expect(
    page.getByText(new RegExp(`转正 ${payload.rotation}°`)),
  ).toBeVisible({ timeout: 60_000 })
  await expect(
    page.getByText(
      new RegExp(
        `方向 ${payload.orientation_ms} ms · Gemini ${payload.layout_ms} ms · 精修 ${payload.refinement_ms} ms`,
      ),
    ),
  ).toBeVisible()
  await expect(page.getByTestId(/^candidate-list-/)).toHaveCount(
    payload.data.length,
  )
  await expect(page.getByText(/Gemini \+ 平行线精修/).first()).toBeVisible()

  const canvas = page.getByTestId("region-marking-canvas")
  const image = canvas.locator("img")
  const dimensions = await image.evaluate((node) => ({
    width: node.getBoundingClientRect().width,
    height: node.getBoundingClientRect().height,
    naturalWidth: node.naturalWidth,
    naturalHeight: node.naturalHeight,
  }))
  expect(dimensions.naturalWidth).toBeGreaterThan(dimensions.naturalHeight)
  expect(dimensions.width).toBeGreaterThan(dimensions.height)

  const recognitionResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes("/pages/1/reference-recognition") &&
      response.ok(),
  )
  await expect(page.getByText("识别结果操作")).toBeVisible()
  await expect(page.getByRole("button", { name: "清除本页" })).toBeDisabled()
  await expect(page.getByRole("button", { name: "清除全部" })).toBeDisabled()
  await page.getByRole("button", { name: "识别当前页" }).click()
  const recognition = await (await recognitionResponsePromise).json()
  expect(recognition.results.length).toBeGreaterThan(0)
  expect(recognition.timing.ocrMs).toBeGreaterThan(0)
  expect(recognition.timing.totalElapsedMs).toBeGreaterThan(0)
  await expect(
    page.getByRole("heading", { name: "全卷题目与考生答案汇总" }),
  ).toBeVisible()
  await expect(
    page.getByText(new RegExp(`当前汇总 ${recognition.results.length} 题`)),
  ).toBeVisible()
  await expect(page.getByRole("button", { name: "清除本页" })).toBeEnabled()
  await expect(page.getByRole("button", { name: "清除全部" })).toBeEnabled()

  await page.screenshot({
    path: "/tmp/new-reference-layout.png",
    fullPage: true,
  })
})
