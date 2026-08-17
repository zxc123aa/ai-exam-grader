import { Fragment, type ReactNode } from "react"

/**
 * 轻量数学排版：把 OCR 纯文本里的常见写法渲染成易读形式。
 * 只处理两种确定无害的模式，其余原样输出，避免误伤普通文字：
 * - 简单分数 a/b（数字或单字母）：堆叠分数线形式
 * - 幂 x^2 / x^10：上标形式
 */
const TOKEN_RE =
  /(\b\d+(?:\.\d+)?\s*\/\s*\d+(?:\.\d+)?\b|\b[a-zA-Z]\s*\/\s*\d+\b|\b\d+\s*\/\s*[a-zA-Z]\b|\b[a-zA-Z]\s*\/\s*[a-zA-Z]\b|\^\d+|[a-zA-Z]\^\d+)/g

function Fraction({ top, bottom }: { top: string; bottom: string }) {
  return (
    <span className="mx-0.5 inline-flex flex-col items-center align-middle leading-none">
      <span className="border-b border-current px-0.5">{top}</span>
      <span className="px-0.5">{bottom}</span>
    </span>
  )
}

function renderToken(token: string, key: number): ReactNode {
  const fraction = token.match(
    /^(\d+(?:\.\d+)?|[a-zA-Z])\s*\/\s*(\d+(?:\.\d+)?|[a-zA-Z])$/,
  )
  if (fraction) {
    return <Fraction key={key} top={fraction[1]} bottom={fraction[2]} />
  }
  const power = token.match(/^([a-zA-Z]?)\^(\d+)$/)
  if (power) {
    return (
      <Fragment key={key}>
        {power[1]}
        <sup className="text-[0.75em]">{power[2]}</sup>
      </Fragment>
    )
  }
  return token
}

export function MathText({
  text,
  className,
}: {
  text: string
  className?: string
}) {
  const parts = text.split(TOKEN_RE)
  return (
    <span className={className}>
      {parts.map((part, index) =>
        index % 2 === 1 ? renderToken(part, index) : part,
      )}
    </span>
  )
}
