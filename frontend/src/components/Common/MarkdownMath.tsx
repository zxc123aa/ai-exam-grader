import katex from "katex"
import { Fragment, type ReactNode, useMemo, useState } from "react"
import "katex/dist/katex.min.css"

/** 按 markdown 标题把长文切节：用于解答的逐节卡片浏览。 */
function splitSections(text: string): string[] {
  const sections: string[] = []
  let current: string[] = []
  for (const line of text.split("\n")) {
    if (/^#{2,4}\s/.test(line.trim()) && current.length > 0) {
      sections.push(current.join("\n"))
      current = [line]
    } else {
      current.push(line)
    }
  }
  if (current.length > 0) sections.push(current.join("\n"))
  return sections.filter((section) => section.trim())
}

/** 长解答：支持「逐节卡片」和「全文」两种浏览方式。 */
export function MarkdownMathSections({
  text,
  className,
}: {
  text: string
  className?: string
}) {
  const sections = useMemo(() => splitSections(text), [text])
  const [mode, setMode] = useState<"card" | "full">("card")
  const [index, setIndex] = useState(0)
  if (sections.length < 2) {
    return <MarkdownMath text={text} className={className} />
  }
  const current = Math.min(index, sections.length - 1)
  return (
    <div className={className}>
      <div className="mb-3 flex items-center gap-1 rounded-lg border p-0.5 text-xs">
        <button
          type="button"
          className={`rounded-md px-2.5 py-1 ${mode === "card" ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}
          onClick={() => setMode("card")}
        >
          逐节浏览
        </button>
        <button
          type="button"
          className={`rounded-md px-2.5 py-1 ${mode === "full" ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}
          onClick={() => setMode("full")}
        >
          全文
        </button>
        {mode === "card" && (
          <span className="ml-auto pr-2 text-muted-foreground tabular-nums">
            {current + 1} / {sections.length}
          </span>
        )}
      </div>
      {mode === "card" ? (
        <div>
          <div className="rounded-xl border bg-muted/30 p-4">
            <MarkdownMath text={sections[current]} />
          </div>
          <div className="mt-3 flex items-center justify-between">
            <button
              type="button"
              className="rounded-md border px-3 py-1.5 text-sm disabled:opacity-40"
              disabled={current === 0}
              onClick={() => setIndex(current - 1)}
            >
              上一节
            </button>
            <button
              type="button"
              className="rounded-md border px-3 py-1.5 text-sm disabled:opacity-40"
              disabled={current >= sections.length - 1}
              onClick={() => setIndex(current + 1)}
            >
              下一节
            </button>
          </div>
        </div>
      ) : (
        <MarkdownMath text={text} />
      )}
    </div>
  )
}

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
      // biome-ignore lint/security/noDangerouslySetInnerHtml: KaTeX 自生成 HTML，无用户输入注入
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

function renderInline(text: string): ReactNode[] {
  // 先按公式分隔符切，再在每个文本段里处理 **加粗** 和 `行内代码`
  const parts = text.split(/(\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\])/)
  return parts.map((part, index) => {
    const inlineMath = part.match(/^\\\(([\s\S]*?)\\\)$/)
    if (inlineMath) return renderMath(inlineMath[1], false, index)
    const displayMath = part.match(/^\\\[([\s\S]*?)\\\]$/)
    if (displayMath) return renderMath(displayMath[1], true, index)
    const boldParts = part.split(/\*\*([\s\S]+?)\*\*/)
    return (
      <Fragment key={index}>
        {boldParts.map((segment, i) => {
          if (i % 2 === 1) return <strong key={i}>{segment}</strong>
          const codeParts = segment.split(/`([^`]+)`/)
          return codeParts.map((piece, j) =>
            j % 2 === 1 ? (
              <code
                key={`${i}-${j}`}
                className="rounded bg-muted px-1 py-0.5 font-mono text-[0.9em]"
              >
                {piece}
              </code>
            ) : (
              piece
            ),
          )
        })}
      </Fragment>
    )
  })
}

/** 表格行拆单元格：去掉首尾 | 再按 | 切。 */
function parseTableRow(line: string): string[] {
  const stripped = line.replace(/^\|/, "").replace(/\|$/, "")
  return stripped.split("|").map((cell) => cell.trim())
}

/**  markdown 表格块：每行以 | 开头，且第二行是 |---| 分隔行。 */
function isTableBlock(lines: string[]): boolean {
  return (
    lines.length >= 2 &&
    lines.every((line) => line.startsWith("|")) &&
    /^\|[\s:|-]+\|$/.test(lines[1])
  )
}

function renderTable(lines: string[], key: number) {
  const rows = lines.filter((_, i) => i !== 1).map(parseTableRow)
  const [head, ...body] = rows
  return (
    <div key={key} className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            {head.map((cell, ci) => (
              <th
                key={ci}
                className="whitespace-nowrap border-b px-2 py-1.5 text-left font-medium"
              >
                {renderInline(cell)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, ri) => (
            <tr key={ri} className="border-b border-border/50 last:border-0">
              {row.map((cell, ci) => (
                <td key={ci} className="px-2 py-1.5 align-top">
                  {renderInline(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function blockClass(marker: string): string {
  if (marker === "###") return "mt-3 font-semibold text-sm"
  if (marker === "##") return "mt-3 font-semibold text-[15px]"
  if (marker === "#") return "mt-2 font-semibold text-base"
  // #### 及更深：按小标题处理，别让 # 裸露出来
  return "mt-2 font-medium text-muted-foreground text-sm"
}

export function MarkdownMath({
  text,
  className,
}: {
  text: string
  className?: string
}) {
  // ``` 围栏只是排版噪音（模型常用它包算式），剥掉留内容
  const cleaned = text.replace(/```[a-zA-Z]*\n?/g, "").replace(/```/g, "")
  const blocks = cleaned.split(/\n{2,}/)
  return (
    <div className={className}>
      {blocks.map((block, index) => {
        const trimmed = block.trim()
        if (!trimmed) return null
        const lines = trimmed
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean)
        if (isTableBlock(lines)) return renderTable(lines, index)
        const header = trimmed.match(/^(#{1,6})\s+(.*)$/s)
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
