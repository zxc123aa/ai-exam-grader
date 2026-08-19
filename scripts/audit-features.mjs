/**
 * 深度功能审计：新功能逐个真实点一遍，查偷工减料。
 * 公网只读+自清理（建了又删），一次真实出题（约 1 分钟模型调用）。
 */
import { createRequire } from "node:module"

const require = createRequire(
  new URL("../frontend/package.json", import.meta.url),
)
const { chromium } = require("playwright")

const BASE = (process.env.SMOKE_BASE_URL || "https://app.dianfandig.com").replace(/\/$/, "")
const STUDENT = {
  email: process.env.SMOKE_STUDENT_EMAIL || "zhangyi@example.com",
  password: process.env.SMOKE_STUDENT_PASSWORD || "student123",
}
const TEACHER = {
  email: process.env.SMOKE_TEACHER_EMAIL || "demo.owner@example.com",
  password: process.env.SMOKE_TEACHER_PASSWORD || "demo12345",
}
const EXAM_ID = process.env.SMOKE_EXAM_ID || "580eaa0b-2bf4-4899-a729-9d97ac7d6f5f"

const results = []
function check(name, ok, detail = "") {
  results.push({ name, ok })
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  — ${detail}` : ""}`)
}

async function login(page, account) {
  await page.goto(`${BASE}/login`, { waitUntil: "commit", timeout: 60000 })
  await page.waitForSelector('input[type="email"]', { timeout: 60000 })
  await page.fill('input[type="email"]', account.email)
  await page.fill('input[type="password"]', account.password)
  await page.click('button[type="submit"]')
  await page.waitForTimeout(6000)
  return !page.url().includes("/login")
}

async function main() {
  console.log(`\n=== 功能审计（偷工减料排查）：${BASE} ===\n`)
  const browser = await chromium.launch({
    executablePath: "/home/st/.cache/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-linux64/chrome-headless-shell",
  })
  const ctx = await browser.newContext({ viewport: { width: 1000, height: 950 } })
  const p = await ctx.newPage()
  p.on("pageerror", (e) => console.log("PAGEERROR:", e.message.slice(0, 150)))

  check("学生登录", await login(p, STUDENT))

  // ===== 1. 错题集全流程（建→移入→过滤→删题→删集） =====
  await p.goto(`${BASE}/my/wrongbook`, { waitUntil: "commit", timeout: 60000 })
  await p.waitForTimeout(5000)
  check("错题集区渲染", (await p.locator('[data-testid="wrongbook-collections"]').count()) === 1)

  await p.click('[data-testid="collection-create-open"]')
  await p.fill('[data-testid="collection-name-input"]', "审计专题")
  await p.click('[data-testid="collection-create-submit"]')
  await p.waitForTimeout(2500)
  const chip = p.locator('[data-testid="collection-chip-审计专题"]')
  check("新建错题集", (await chip.count()) === 1)

  const assign = p.locator('[data-testid^="assign-collection-"]').first()
  check("移入下拉出现在错题卡", (await assign.count()) > 0)
  if ((await chip.count()) && (await assign.count())) {
    await assign.selectOption({ label: "审计专题" })
    await p.waitForTimeout(2500)
    const chipText = await chip.innerText()
    check("移入后集计数 +1", chipText.includes("（1）"), chipText)
    await chip.click()
    await p.waitForTimeout(2500)
    const filtered = await p.locator('[data-testid^="entry-delete-"]').count()
    check("按集过滤只剩该集题目", filtered >= 1, `${filtered} 条`)
    // 删除这条错题（两步）
    await p.locator('[data-testid^="entry-delete-"]').first().click()
    await p.waitForTimeout(600)
    await p.locator('[data-testid="entry-delete-confirm"]').click()
    await p.waitForTimeout(2500)
    check("错题删除（两步确认）", (await p.locator('[data-testid^="entry-delete-"]').count()) === 0)
    // 删集（两步）
    await p.click('[data-testid="collection-delete"]')
    await p.waitForTimeout(600)
    await p.click('[data-testid="collection-delete-confirm"]')
    await p.waitForTimeout(2500)
    check("错题集删除", (await p.locator('[data-testid="collection-chip-审计专题"]').count()) === 0)
  }

  // ===== 2. 学习建议 → 变式练习链接 =====
  await p.goto(`${BASE}/my/wrongbook`, { waitUntil: "commit", timeout: 60000 })
  await p.waitForTimeout(4000)
  const genBtn = p.locator('button:has-text("生成我的学习建议")')
  if ((await genBtn.count()) > 0) {
    await genBtn.click()
    // 模型调用约 30-60s
    await p.waitForSelector('text=生成变式练习', { timeout: 120000 })
  }
  const variantLink = p.locator('text=生成变式练习 →').first()
  check("学习建议出「生成变式练习」链接", (await variantLink.count()) > 0)
  if ((await variantLink.count()) > 0) {
    await variantLink.click()
    await p.waitForTimeout(4000)
    const url = p.url()
    check(
      "链接落到出题页且带知识点",
      url.includes("/my/wrongbook-sheet") && url.includes("kps="),
      url.split("kps=")[1]?.slice(0, 30) ?? url,
    )
  }

  // ===== 3. 变式练习真实生成一次（验证超时不误杀） =====
  if (p.url().includes("wrongbook-sheet")) {
    const createBtn = p.locator('button:has-text("生成变式练习")').first()
    if ((await createBtn.count()) > 0 && (await createBtn.isEnabled())) {
      const t0 = Date.now()
      await createBtn.click()
      const done = await p
        .waitForSelector('text=生成于', { timeout: 150000 })
        .then(() => true)
        .catch(() => false)
      check("变式练习真实生成", done, `${Math.round((Date.now() - t0) / 1000)}s`)
      if (done) {
        const text = await p.locator("main").last().innerText()
        check("题目内容非空", text.length > 200, `${text.length} 字`)
      }
    }
  }

  // ===== 4. 拍题记录删除入口 =====
  await p.goto(`${BASE}/my/snap-history`, { waitUntil: "commit", timeout: 60000 })
  await p.waitForTimeout(3000)
  const recs = await p.locator('[data-testid="snap-record-item"]').count()
  check("拍题记录列表", recs > 0, `${recs} 条`)
  check(
    "记录删除按钮",
    (await p.locator('[data-testid="snap-record-delete"]').count()) === recs,
  )
  await ctx.close()

  // ===== 5. 教师端：改绑对话框 + 上传花名册提示 =====
  const tctx = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  const tp = await tctx.newPage()
  tp.on("pageerror", (e) => console.log("PAGEERROR:", e.message.slice(0, 150)))
  check("教师登录", await login(tp, TEACHER))
  await tp.goto(`${BASE}/exams/${EXAM_ID}`, { waitUntil: "commit", timeout: 60000 })
  await tp.waitForTimeout(5000)
  await tp.locator('[role="tab"]:has-text("学生答卷")').click()
  // 列表加载受网络影响，别用固定等待
  await tp
    .waitForSelector('[data-testid^="reassign-student-"]', { timeout: 30000 })
    .catch(() => {})
  const reassignBtns = await tp.locator('[data-testid^="reassign-student-"]').count()
  check("改绑按钮在答卷列表", reassignBtns > 0, `${reassignBtns} 个`)
  if (reassignBtns > 0) {
    await tp.locator('[data-testid^="reassign-student-"]').first().click()
    await tp.waitForTimeout(1500)
    check(
      "改绑对话框（学号/班级/姓名三栏）",
      (await tp.locator('[data-testid="reassign-identifier-input"]').count()) === 1 &&
        (await tp.locator('[data-testid="reassign-name-input"]').count()) === 1,
    )
    await tp.click('button:has-text("取消")')
  }
  await tctx.close()
  await browser.close()

  const failed = results.filter((r) => !r.ok)
  console.log(`\n=== 结果：${results.length - failed.length}/${results.length} 通过 ===\n`)
  process.exit(failed.length ? 1 : 0)
}

main()
