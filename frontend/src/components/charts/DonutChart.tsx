import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts"

import { CHART_PALETTE, PRIMARY_COLOR, TOOLTIP_STYLE } from "./theme"

/**
 * 环形图（对齐原型 donutChart），两种用法互斥：
 * - 传 value：单值环形进度，中心显示 label/sub；
 * - 传 segments：多段环形 + 下方图例，中心显示合计。
 */
export interface DonutSegment {
  name: string
  value: number
  /** 缺省按 chart-1..5 色板循环 */
  color?: string
}

type DonutProps = {
  size?: number
  /** 环宽 */
  stroke?: number
  className?: string
} & (
  | {
      /** 进度环：0-100 */
      value: number
      /** 中心主文案，如 "86%" */
      label?: string
      /** 中心副文案 */
      sub?: string
      color?: string
      segments?: never
    }
  | {
      segments: DonutSegment[]
      value?: never
      label?: never
      sub?: never
      color?: never
    }
)

export function DonutChart(props: DonutProps) {
  const { size = 160, stroke = 16, className } = props

  if (props.segments) {
    const segments = props.segments
    const total = segments.reduce((s, x) => s + x.value, 0)
    const data = segments.map((s, i) => ({
      ...s,
      color: s.color ?? CHART_PALETTE[i % CHART_PALETTE.length],
    }))
    return (
      <div className={className}>
        <div className="relative mx-auto" style={{ width: size, height: size }}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                dataKey="value"
                nameKey="name"
                innerRadius={(size - stroke) / 2}
                outerRadius={size / 2}
                strokeWidth={0}
                startAngle={90}
                endAngle={-270}
              >
                {data.map((d) => (
                  <Cell key={d.name} fill={d.color} />
                ))}
              </Pie>
              <Tooltip contentStyle={TOOLTIP_STYLE} />
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <span className="font-bold text-2xl tabular-nums">{total}</span>
            <span className="text-muted-foreground text-xs">总计</span>
          </div>
        </div>
        <ul className="mt-3 flex flex-wrap justify-center gap-x-4 gap-y-1.5">
          {data.map((d) => (
            <li key={d.name} className="flex items-center gap-1.5 text-xs">
              <span
                className="size-2 rounded-full"
                style={{ background: d.color }}
              />
              <span className="text-muted-foreground">{d.name}</span>
              <span className="font-medium tabular-nums">{d.value}</span>
            </li>
          ))}
        </ul>
      </div>
    )
  }

  /* 单值进度环 */
  const v = Math.min(100, Math.max(0, props.value))
  const color = props.color ?? PRIMARY_COLOR
  const data = [
    { name: "done", value: v },
    { name: "rest", value: 100 - v },
  ]
  return (
    <div
      className={className}
      style={{ position: "relative", width: size, height: size }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            innerRadius={(size - stroke) / 2}
            outerRadius={size / 2}
            strokeWidth={0}
            startAngle={90}
            endAngle={-270}
            cornerRadius={stroke / 2}
            isAnimationActive={false}
          >
            <Cell fill={color} />
            <Cell fill="var(--secondary)" />
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-bold text-2xl tabular-nums">
          {props.label ?? `${Math.round(v)}%`}
        </span>
        {props.sub && (
          <span className="mt-0.5 text-muted-foreground text-xs">
            {props.sub}
          </span>
        )}
      </div>
    </div>
  )
}
