import {
  Bar,
  Cell,
  BarChart as ReBarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { DANGER_COLOR, PRIMARY_COLOR, TICK_PROPS, TOOLTIP_STYLE } from "./theme"

/**
 * 横向条形图（各题得分率，对齐原型 hbarChart）。
 * value 视为 0-100 的百分比；低于 threshold 的条形标红警示，其余用主色。
 */
export function HBarChart({
  items,
  threshold = 60,
  rowHeight = 32,
  labelWidth = 110,
}: {
  items: { label: string; value: number }[]
  /** 低于该值标红，默认 60 */
  threshold?: number
  rowHeight?: number
  labelWidth?: number
}) {
  return (
    <ResponsiveContainer width="100%" height={items.length * rowHeight + 8}>
      <ReBarChart
        data={items}
        layout="vertical"
        margin={{ top: 0, right: 36, bottom: 0, left: 0 }}
      >
        <XAxis type="number" domain={[0, 100]} hide />
        <YAxis
          type="category"
          dataKey="label"
          width={labelWidth}
          tickLine={false}
          axisLine={false}
          tick={{ ...TICK_PROPS, fontSize: 12, fill: "var(--foreground)" }}
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          cursor={{ fill: "var(--accent)" }}
          formatter={(value) => [`${value}%`, "得分率"]}
        />
        <Bar dataKey="value" radius={[0, 6, 6, 0]} barSize={rowHeight - 16}>
          {items.map((it) => (
            <Cell
              key={it.label}
              fill={it.value < threshold ? DANGER_COLOR : PRIMARY_COLOR}
            />
          ))}
        </Bar>
      </ReBarChart>
    </ResponsiveContainer>
  )
}
