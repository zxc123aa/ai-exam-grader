import { ClipboardCheck, PenLine, ScanLine } from "lucide-react"

import { Appearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import { Footer } from "./Footer"

interface AuthLayoutProps {
  children: React.ReactNode
}

const highlights = [
  {
    icon: ScanLine,
    title: "扫描并重建空白试卷",
    description: "支持 PDF 与照片上传、页面预览和题目区域标注",
  },
  {
    icon: PenLine,
    title: "标准答案与评分规则",
    description: "按题设置参考答案、满分和评分要点",
  },
  {
    icon: ClipboardCheck,
    title: "AI 初评，教师定稿",
    description: "OCR 与评分草稿经教师复核后才计入成绩",
  },
]

export function AuthLayout({ children }: AuthLayoutProps) {
  return (
    <div className="grid min-h-svh lg:grid-cols-2">
      <div className="relative hidden overflow-hidden bg-sidebar text-sidebar-foreground lg:flex lg:flex-col lg:justify-between lg:p-10">
        <div
          aria-hidden
          className="pointer-events-none absolute -top-32 -right-32 size-96 rounded-full bg-indigo-500/20 blur-3xl"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -bottom-40 -left-24 size-96 rounded-full bg-indigo-400/10 blur-3xl"
        />
        <Logo variant="full" asLink={false} className="relative" />
        <div className="relative flex flex-col gap-8">
          <div className="flex flex-col gap-3">
            <p className="text-3xl font-semibold leading-tight text-sidebar-accent-foreground">
              让纸质试卷批改
              <br />
              更准确、更高效
            </p>
            <p className="max-w-md text-sm text-sidebar-foreground/70">
              将空白试卷重建为模板，关联标准答案，并逐题复核 AI 生成的评分草稿。
            </p>
          </div>
          <ul className="flex flex-col gap-5">
            {highlights.map((item) => (
              <li key={item.title} className="flex items-start gap-3">
                <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-sidebar-accent text-sidebar-accent-foreground">
                  <item.icon className="size-4" />
                </span>
                <span className="flex flex-col">
                  <span className="text-sm font-medium text-sidebar-accent-foreground">
                    {item.title}
                  </span>
                  <span className="text-xs text-sidebar-foreground/60">
                    {item.description}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-sidebar-foreground/50">
          扫描 · 标注 · 批改 · 复核
        </p>
      </div>
      <div className="flex flex-col gap-4 p-6 md:p-10">
        <div className="flex items-center justify-between lg:justify-end">
          <span className="lg:hidden">
            <Logo variant="full" asLink={false} />
          </span>
          <Appearance />
        </div>
        <div className="flex flex-1 items-center justify-center">
          <div className="w-full max-w-sm">{children}</div>
        </div>
        <Footer />
      </div>
    </div>
  )
}
