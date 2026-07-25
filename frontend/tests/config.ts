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

/** 外部 AI 提供者（Gemini 识别 / GPT 批改）是否配置了 API key。 */
export const visionProviderConfigured = Boolean(
  process.env.PROVIDER_FLUXNODE_GEMINI_API_KEY,
)
export const gradingProviderConfigured = Boolean(
  process.env.PROVIDER_POMOAI_API_KEY,
)
