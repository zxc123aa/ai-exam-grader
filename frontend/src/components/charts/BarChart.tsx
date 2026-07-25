import {
  Bar,
  CartesianGrid,
  BarChart as ReBarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { GRID_COLOR, PRIMARY_COLOR, TICK_PROPS, TOOLTIP_STYLE } from "./theme"

/**
 * 柱状图（对齐原型 barChart，如成绩分布直方图）。
 */
export function BarChart({
  labels,
  data,
  unit,
  height = 260,
  color = PRIMARY_COLOR,
}: {
  labels: string[]
  data: number[]
  unit?: string
  height?: number
  color?: string
}) {
  const rows = labels.map((label, i) => ({ label, value: data[i] }))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ReBarChart
        data={rows}
        margin={{ top: 8, right: 12, bottom: 0, left: -16 }}
      >
        <CartesianGrid
          stroke={GRID_COLOR}
          strokeDasharray="4 4"
          vertical={false}
        />
        <XAxis
          dataKey="label"
          tickLine={false}
          axisLine={false}
          tick={TICK_PROPS}
        />
        <YAxis tickLine={false} axisLine={false} tick={TICK_PROPS} />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          cursor={{ fill: "var(--accent)" }}
          formatter={(value) => [`${value}${unit ?? ""}`]}
        />
        <Bar
          dataKey="value"
          fill={color}
          radius={[6, 6, 0, 0]}
          maxBarSize={48}
        />
      </ReBarChart>
    </ResponsiveContainer>
  )
}
