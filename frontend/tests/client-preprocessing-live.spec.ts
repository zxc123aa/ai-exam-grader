import { randomBytes } from "node:crypto"
import { readFileSync } from "node:fs"
import path from "node:path"
import { expect, test } from "@playwright/test"

// 客户端前处理实况验证。
//
// 关键点：saveCorners 先试浏览器里的 OpenCV.js（Web Worker），失败只打一行
// console.warn 就悄悄退回服务端。所以「界面结果正常」并不能说明客户端路径生效，
// 必须看命中的是 upload-preprocessed 还是 preprocess-with-quads，
// 以及产物元数据里的 source。

test.use({ storageState: { cookies: [], origins: [] } })

const API_BASE = "http://localhost:8000/api/v1"
// 测试以 frontend/ 为工作目录运行（与其它实况用例的相对截图路径一致）。
const PHOTO = path.resolve(
  process.cwd(),
  "../参考算法/2_试卷分析文件/material/1.jpg",
)
const OUT_DIR = "../outputs/client-preprocessing"

// 服务端对照用的四角：略微内缩并带一点透视，保证真的做一次单应变换。
const BASELINE_QUAD = [
  { x: 0.03, y: 0.03 },
  { x: 0.97, y: 0.02 },
  { x: 0.98, y: 0.98 },
  { x: 0.02, y: 0.97 },
]

test("四角保存走客户端 OpenCV 前处理，而不是静默回退服务端", async ({
  page,
}) => {
  test.setTimeout(600_000)
  const photo = readFileSync(PHOTO)

  const consoleLines: string[] = []
  page.on("console", (msg) =>
    consoleLines.push(`[${msg.type()}] ${msg.text()}`),
  )
  page.on("pageerror", (err) => consoleLines.push(`[pageerror] ${err.message}`))

  const watched =
    /upload-preprocessed|preprocess-with-quads|auto-rectify|opencv\.js|preprocessor-worker\.js/
  const calls: { path: string; method: string; status: number; ms: number }[] =
    []
  const startedAt = new Map<string, number>()
  page.on("request", (req) => {
    if (watched.test(req.url()))
      startedAt.set(req.url() + req.method(), Date.now())
  })
  page.on("response", (res) => {
    const url = res.url()
    if (!watched.test(url)) return
    const key = url + res.request().method()
    const began = startedAt.get(key)
    calls.push({
      path: url.replace(/^https?:\/\/[^/]+/, ""),
      method: res.request().method(),
      status: res.status(),
      ms: began ? Date.now() - began : -1,
    })
  })

  // ---- 1. 备好学校侧老师账号（平台账号无权直接建考试），建考试并上传真实照片
  //         preprocess=none，让四角保存成为唯一的前处理来源。
  async function loginAs(username: string, password: string) {
    const response = await page.request.post(`${API_BASE}/login/access-token`, {
      form: { username, password },
    })
    expect(
      response.ok(),
      `登录失败 HTTP ${response.status()}: ${await response.text()}`,
    ).toBeTruthy()
    return (await response.json()).access_token as string
  }

  const platformToken = await loginAs(
    process.env.LIVE_TEST_EMAIL ?? "",
    process.env.LIVE_TEST_PASSWORD ?? "",
  )
  const suffix = randomBytes(3).toString("hex")
  const ownerEmail = `preproc-${suffix}@example.com`
  const ownerPassword = randomBytes(12).toString("base64url")
  const orgResponse = await page.request.post(`${API_BASE}/platform/orgs`, {
    headers: { Authorization: `Bearer ${platformToken}` },
    data: {
      name: `客户端前处理试校${suffix}`,
      code: `preproc${suffix}`,
      owner: {
        email: ownerEmail,
        full_name: "前处理验证老师",
        password: ownerPassword,
      },
    },
  })
  expect(
    orgResponse.ok(),
    `建学校失败 HTTP ${orgResponse.status()}: ${await orgResponse.text()}`,
  ).toBeTruthy()

  const token = await loginAs(ownerEmail, ownerPassword)
  const headers = { Authorization: `Bearer ${token}` }

  const examResponse = await page.request.post(`${API_BASE}/exams/`, {
    headers,
    data: {
      title: `客户端前处理验证-${Date.now()}`,
      subject: "物理",
    },
  })
  expect(
    examResponse.ok(),
    `建考试失败 HTTP ${examResponse.status()}: ${await examResponse.text()}`,
  ).toBeTruthy()
  const exam = await examResponse.json()

  async function uploadPhoto(name: string) {
    const response = await page.request.post(
      `${API_BASE}/exams/${exam.id}/files`,
      {
        headers,
        multipart: {
          file: { name, mimeType: "image/jpeg", buffer: photo },
          document_type: "blank_exam",
          preprocess: "none",
        },
      },
    )
    expect(response.ok()).toBeTruthy()
    return response.json()
  }

  const clientDoc = await uploadPhoto("client-path.jpg")
  expect(clientDoc.preprocessing_status).toBe("not_required")

  // ---- 2. 界面：导入试卷 → 复核四角 → 确认四角并保存
  await page.goto("/login")
  await page.evaluate(
    (value) => localStorage.setItem("access_token", value),
    token,
  )
  await page.goto(`/exams/${exam.id}/marking`)
  await page.getByRole("button", { name: "导入试卷" }).click()

  const filesDialog = page.getByRole("dialog")
  await expect(
    filesDialog.getByText("client-path.jpg", { exact: true }),
  ).toBeVisible({ timeout: 30_000 })
  await filesDialog.getByRole("button", { name: "复核四角" }).first().click()

  const editor = page.getByRole("dialog").filter({ hasText: "复核纸面四角" })
  const apply = editor.getByRole("button", { name: /确认四角/ })
  await expect(apply).toBeVisible({ timeout: 90_000 })
  await editor.screenshot({ path: `${OUT_DIR}/1-corner-editor.png` })

  const savedAt = Date.now()
  await apply.click()
  // 两条路径都会在成功后关闭对话框，所以先等它关，再看命中的是哪个接口。
  await expect(editor).toBeHidden({ timeout: 240_000 })
  const saveMs = Date.now() - savedAt

  const clientCalls = calls.filter((c) =>
    c.path.includes("upload-preprocessed"),
  )
  const serverCalls = calls.filter((c) =>
    c.path.includes("preprocess-with-quads"),
  )
  const opencvCall = calls.find((c) => c.path.includes("opencv.js"))
  const fallbackWarn = consoleLines.filter((line) =>
    line.includes("Client preprocessing failed"),
  )

  // ---- 3. 服务端老路径对照（同一张照片、另一个文档）
  const serverDoc = await uploadPhoto("server-path.jpg")
  const baselineAt = Date.now()
  const baseline = await page.request.post(
    `${API_BASE}/exams/${exam.id}/files/${serverDoc.id}/preprocess-with-quads`,
    {
      headers,
      data: {
        detector: "baseline_manual",
        margin_mode: "minimal",
        pages: [{ label: "single", points: BASELINE_QUAD }],
      },
      timeout: 240_000,
    },
  )
  const baselineMs = Date.now() - baselineAt
  expect(baseline.ok()).toBeTruthy()

  // ---- 4. 产物元数据核对
  const filesResponse = await page.request.get(
    `${API_BASE}/exams/${exam.id}/files`,
    { headers },
  )
  const documents = (await filesResponse.json()).data
  const updatedClientDoc = documents.find(
    (item: { id: string }) => item.id === clientDoc.id,
  )
  const updatedServerDoc = documents.find(
    (item: { id: string }) => item.id === serverDoc.id,
  )

  console.log(
    "\n================ 客户端前处理实况结果 ================\n" +
      `考试：${exam.title}  (${exam.id})\n` +
      `照片：material/1.jpg  ${(photo.length / 1024).toFixed(0)} KB\n\n` +
      `opencv.js 下载：${opencvCall ? `${opencvCall.ms} ms / HTTP ${opencvCall.status}` : "未请求"}\n` +
      `点“确认四角并保存”到对话框关闭：${saveMs} ms\n` +
      `命中 upload-preprocessed：${clientCalls.length} 次 ${JSON.stringify(clientCalls)}\n` +
      `命中 preprocess-with-quads（回退）：${serverCalls.length} 次 ${JSON.stringify(serverCalls)}\n` +
      `回退告警：${fallbackWarn.length ? fallbackWarn.join(" | ") : "无"}\n\n` +
      `客户端告警：${JSON.stringify(
        updatedClientDoc?.preprocessing_metadata?.quality?.warnings ?? null,
      )}\n` +
      `服务端告警：${JSON.stringify(
        updatedServerDoc?.preprocessing_metadata?.quality?.warnings ?? null,
      )}\n\n` +
      `客户端路径产物：status=${updatedClientDoc?.preprocessing_status} ` +
      `quality=${updatedClientDoc?.preprocessing_quality} ` +
      `source=${updatedClientDoc?.preprocessing_metadata?.source} ` +
      `engine=${updatedClientDoc?.preprocessing_metadata?.debug?.engine} ` +
      `detector=${updatedClientDoc?.preprocessing_metadata?.detector} ` +
      `pdf=${updatedClientDoc?.stored_file?.original_filename} ` +
      `${((updatedClientDoc?.stored_file?.size_bytes ?? 0) / 1024).toFixed(0)} KB\n` +
      `服务端对照产物：耗时 ${baselineMs} ms status=${updatedServerDoc?.preprocessing_status} ` +
      `quality=${updatedServerDoc?.preprocessing_quality} ` +
      `source=${updatedServerDoc?.preprocessing_metadata?.source} ` +
      `${((updatedServerDoc?.stored_file?.size_bytes ?? 0) / 1024).toFixed(0)} KB\n` +
      "=====================================================\n",
  )

  // 保存成功后对话框会自动关闭，重新打开拍一张处理后的样子。
  // 处理完成后行内显示的是生成的 PDF 名，不再是原始 jpg，所以只等对话框本身。
  // 截图纯属留证，失败不能掩盖下面的真实断言。
  try {
    await page.getByRole("button", { name: "导入试卷" }).click()
    const reopened = page.getByRole("dialog").first()
    await expect(
      reopened.getByText("整张卷子的页面顺序", { exact: true }),
    ).toBeVisible({ timeout: 30_000 })
    await reopened.screenshot({ path: `${OUT_DIR}/2-after-scan.png` })
  } catch (screenshotErr) {
    console.log(`截图步骤跳过：${screenshotErr}`)
  }

  // 客户端路径必须真的生效：命中新接口、没有回退、元数据打上客户端标记。
  expect(clientCalls.length, "应命中 upload-preprocessed").toBeGreaterThan(0)
  expect(clientCalls[0].status).toBe(200)
  expect(fallbackWarn, "不应出现静默回退告警").toEqual([])
  expect(serverCalls, "不应回退到 preprocess-with-quads").toEqual([])
  expect(updatedClientDoc.preprocessing_metadata.source).toBe(
    "client_preprocessed_upload_v1",
  )
  expect(updatedClientDoc.preprocessing_metadata.debug.engine).toBe(
    "client_opencvjs_upload_v1",
  )
  expect(updatedClientDoc.stored_file.original_filename).toContain(
    "client-scanned.pdf",
  )

  // 两条路径的质量口径必须一致：preprocessing_status 只能是界面认得的值
  // （不能把内部的 "pass" 泄漏到徽章上），且质量告警要真的参与计算。
  expect(["ready", "review"], "preprocessing_status 不应出现内部值").toContain(
    updatedClientDoc.preprocessing_status,
  )
  expect(
    Array.isArray(updatedClientDoc.preprocessing_metadata.quality.warnings),
    "客户端路径应产出质量告警字段",
  ).toBe(true)
})
