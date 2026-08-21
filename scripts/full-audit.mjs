/**
 * 全面自测巡检：双端全页面 + 越权 + 边界，截图供人工审阅。
 * node scripts/full-audit.mjs
 * 产物：outputs/audit/<name>.png + 控制台/页面错误汇总
 */
import { createRequire } from "node:module"
import { mkdirSync } from "node:fs"

const require = createRequire(
  new URL("../frontend/package.json", import.meta.url),
)
const { chromium } = require("playwright")

const BASE = process.env.SMOKE_BASE_URL || "https://app.dianfandig.com"
const OUT = new URL("../outputs/audit/", import.meta.url).pathname
mkdirSync(OUT, { recursive: true })

const STUDENT = { email: "zhangyi@example.com", password: "student123" }
const TEACHER = { email: "demo.owner@example.com", password: "demo12345" }
const EXAM = "580eaa0b-2bf4-4899-a729-9d97ac7d6f5f"

const issues = []
function issue(severity, where, what) {
  issues.push({ severity, where, what })
  console.log(`[${severity}] ${where}: ${what}`)
}

async function login(p, account) {
  await p.goto(`${BASE}/login`, { waitUntil: "commit", timeout: 60000 })
  await p.waitForSelector('input[type="email"]', { timeout: 60000 })
  await p.fill('input[type="email"]', account.email)
  await p.fill('input[type="password"]', account.password)
  await p.click('button[type="submit"]')
  await p.waitForTimeout(6000)
}

async function sweep(p, path, name, { wait = 4000, shot = true } = {}) {
  const errors = []
  const onErr = (e) => errors.push(e.message.slice(0, 150))
  p.on("pageerror", onErr)
  const respErrors = []
  const onResp = (r) => {
    if (r.status() >= 500 && !r.url().includes("hot-update")) respErrors.push(`${r.status()} ${r.url().slice(-60)}`)
  }
  p.on("response", onResp)
  await p.goto(`${BASE}${path}`, { waitUntil: "commit", timeout: 60000 }).catch((e) => {
    issue("P1", name, `导航失败 ${e.message.slice(0, 80)}`)
  })
  await p.waitForTimeout(wait)
  const errorPage = await p.locator('[data-testid="error-component"]').count()
  if (errorPage) {
    const msg = await p.locator('[data-testid="error-component"]').innerText().catch(() => "")
    issue("P0", name, `全局错误页: ${msg.slice(0, 120).replace(/\n/g, " ")}`)
  }
  if (errors.length) issue("P1", name, `JS 异常: ${errors[0]}`)
  if (respErrors.length) issue("P1", name, `接口 5xx: ${respErrors[0]}`)
  if (shot) await p.screenshot({ path: `${OUT}${name}.png`, fullPage: false }).catch(() => {})
  p.off("pageerror", onErr)
  p.off("response", onResp)
  console.log(`done ${name}`)
}

const browser = await chromium.launch({
  executablePath: "/home/st/.cache/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-linux64/chrome-headless-shell",
})

// ===== 学生端 =====
const sctx = await browser.newContext({ viewport: { width: 1000, height: 950 } })
const sp = await sctx.newPage()
await login(sp, STUDENT)
for (const [path, name] of [
  ["/my/exams", "s-成绩列表"],
  ["/my/snap", "s-拍题答疑"],
  ["/my/snap-history", "s-拍题记录"],
  ["/my/wrongbook", "s-错题本"],
  ["/my/knowledge", "s-知识图谱"],
  ["/my/wrongbook-sheet", "s-错题卷"],
]) {
  await sweep(sp, path, name)
}
// 成绩详情页（有发布的考试才进得去）
await sweep(sp, "/my/exams", "s-成绩列表2", { shot: false })
const examLink = sp.locator('a[href*="/my/exams/"]').first()
if ((await examLink.count()) > 0) {
  const href = await examLink.getAttribute("href")
  await sweep(sp, href, "s-成绩详情", { wait: 6000 })
}
// 越权：学生访问教师/管理页面
for (const [path, name] of [
  ["/exams", "x-学生访考试管理"],
  ["/admin", "x-学生访用户管理"],
  ["/platform", "x-学生访平台管理"],
]) {
  await sweep(sp, path, name, { shot: false })
  const text = await sp.locator("body").innerText().catch(() => "")
  if (text.includes("考试管理") && name === "x-学生访考试管理") {
    issue("P0", name, "学生能看到教师考试管理页")
  }
}
// 手机视口错题本
await sp.setViewportSize({ width: 390, height: 844 })
await sweep(sp, "/my/wrongbook", "s-错题本-手机", { wait: 5000 })
await sctx.close()

// ===== 教师端 =====
const tctx = await browser.newContext({ viewport: { width: 1360, height: 950 } })
const tp = await tctx.newPage()
await login(tp, TEACHER)
for (const [path, name] of [
  ["/", "t-工作台"],
  ["/exams", "t-考试管理"],
  [`/exams/${EXAM}`, "t-导入试卷"],
  [`/exams/${EXAM}/questions`, "t-确认题目"],
  [`/exams/${EXAM}/answers`, "t-标准答案"],
  [`/exams/${EXAM}/grading`, "t-批改复核"],
  [`/exams/${EXAM}/workbench`, "t-批卷工作台"],
  [`/exams/${EXAM}/scores`, "t-成绩"],
  [`/exams/${EXAM}/report`, "t-改卷报告"],
  ["/classes", "t-班级学生"],
  ["/advanced-settings", "t-高级设置"],
  ["/admin", "t-用户管理"],
  ["/org-settings", "t-学校设置"],
]) {
  await sweep(tp, path, name, { wait: 5000 })
}
// 越权：教师访问平台管理
await sweep(tp, "/platform", "x-教师访平台", { shot: false })
// 不存在路由
await sweep(tp, "/no-such-page", "x-404页面", { shot: false })
const nf = await tp.locator("body").innerText()
if (!nf.includes("404") && !nf.includes("不存在") && !nf.includes("Not Found")) {
  issue("P2", "x-404页面", "未知路径没有 404 提示")
}
await tctx.close()
await browser.close()

console.log(`\n===== 巡检完成：发现 ${issues.length} 个问题 =====`)
issues.forEach((i) => console.log(`[${i.severity}] ${i.where}: ${i.what}`))
