import katex from "katex"
import { Fragment, type ReactNode } from "react"
import "katex/dist/katex.min.css"

/**
 * 轻量 Markdown+公式渲染：给模型生成的解答文本用。
 * 支持：#/##/### 标题、**加粗**、\(...\) 行内公式、\[...\] 独立公式。
 * 公式经 KaTeX 渲染（throwOnError: false，坏公式原样显示不炸页面）。
 */

function renderMath(latex: string, displayMode: boolean, key: number) {
  const html = katex.renderToString(latex, {
    throwOnError: false,
    displayMode,
    strict: false,
  })
  return (
    <span
      key={key}
      className={displayMode ? "my-2 block overflow-x-auto" : undefined}
      // KaTeX 输出是自身生成的安全 HTML
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

function renderInline(text: string): ReactNode[] {
  // 先按公式分隔符切，再在每个文本段里处理 **加粗**
  const parts = text.split(/(\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\])/)
  return parts.map((part, index) => {
    const inlineMath = part.match(/^\\\(([\s\S]*?)\\\)$/)
    if (inlineMath) return renderMath(inlineMath[1], false, index)
    const displayMath = part.match(/^\\\[([\s\S]*?)\\\]$/)
    if (displayMath) return renderMath(displayMath[1], true, index)
    const boldParts = part.split(/\*\*([^*]+)\*\*/)
    return (
      <Fragment key={index}>
        {boldParts.map((segment, i) =>
          i % 2 === 1 ? <strong key={i}>{segment}</strong> : segment,
        )}
      </Fragment>
    )
  })
}

function blockClass(marker: string): string {
  if (marker === "###") return "mt-3 font-semibold text-sm"
  if (marker === "##") return "mt-3 font-semibold text-[15px]"
  return "mt-2 font-semibold text-base"
}

export function MarkdownMath({
  text,
  className,
}: {
  text: string
  className?: string
}) {
  const blocks = text.split(/\n{2,}/)
  return (
    <div className={className}>
      {blocks.map((block, index) => {
        const trimmed = block.trim()
        if (!trimmed) return null
        const header = trimmed.match(/^(#{1,3})\s+(.*)$/s)
        if (header) {
          return (
            <div key={index} className={blockClass(header[1])}>
              {renderInline(header[2])}
            </div>
          )
        }
        return (
          <div key={index} className="whitespace-pre-wrap leading-7">
            {renderInline(trimmed)}
          </div>
        )
      })}
    </div>
  )
}
