import {
  CartesianGrid,
  Line,
  LineChart as ReLineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { CHART_PALETTE, GRID_COLOR, TICK_PROPS, TOOLTIP_STYLE } from "./theme"

/**
 * 折线图（多序列，对齐原型 lineChart）。
 * labels 为 X 轴类目，series 为多条数据线；第一条序列带渐变面积。
 */
export interface LineSeries {
  name: string
  /** null 表示该场次缺数据（知识点没出现），线条在此断开 */
  data: (number | null)[]
  /** 缺省按 chart-1..5 色板循环 */
  color?: string
}

export function LineChart({
  labels,
  series,
  unit,
  yMin,
  yMax,
  height = 260,
}: {
  labels: string[]
  series: LineSeries[]
  /** 数值单位，tooltip 中追加显示 */
  unit?: string
  yMin?: number
  yMax?: number
  height?: number
}) {
  const data = labels.map((label, i) => ({
    label,
    ...Object.fromEntries(series.map((s) => [s.name, s.data[i]])),
  }))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ReLineChart
        data={data}
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
        <YAxis
          tickLine={false}
          axisLine={false}
          tick={TICK_PROPS}
          domain={[yMin ?? "auto", yMax ?? "auto"]}
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          formatter={(value) => [`${value}${unit ?? ""}`]}
        />
        {series.map((s, i) => (
          <Line
            key={s.name}
            type="monotone"
            dataKey={s.name}
            stroke={s.color ?? CHART_PALETTE[i % CHART_PALETTE.length]}
            strokeWidth={2.5}
            dot={{ r: 3, strokeWidth: 2 }}
            activeDot={{ r: 5 }}
          />
        ))}
      </ReLineChart>
    </ResponsiveContainer>
  )
}
