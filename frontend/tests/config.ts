import path from "node:path"
import { fileURLToPath } from "node:url"
import dotenv from "dotenv"

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

dotenv.config({ path: path.join(__dirname, "../../.env") })

function getEnvVar(name: string): string {
  const value = process.env[name]
  if (!value) {
    throw new Error(`Environment variable ${name} is undefined`)
  }
  return value
}

export const firstSuperuser = getEnvVar("FIRST_SUPERUSER")
export const firstSuperuserPassword = getEnvVar("FIRST_SUPERUSER_PASSWORD")

// 学校侧 E2E 账号（默认学校的 school_owner）。角色收紧后平台超管会被引导到
// /platform 且进不了学校业务页，所以学校页面的测试一律用这个账号。
export const schoolOwnerEmail = "demo.owner@example.com"
export const schoolOwnerPassword = "password123"

/** 外部 AI 提供者（Gemini 识别 / GPT 批改）是否配置了 API key。 */
export const visionProviderConfigured = Boolean(
  process.env.PROVIDER_FLUXNODE_GEMINI_API_KEY,
)
export const gradingProviderConfigured = Boolean(
  process.env.PROVIDER_POMOAI_API_KEY,
)
