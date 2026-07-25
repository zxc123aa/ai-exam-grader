import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart as ReRadarChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts"

import { GRID_COLOR, PRIMARY_COLOR, TICK_PROPS, TOOLTIP_STYLE } from "./theme"

/**
 * 雷达图（知识点掌握度，对齐原型 radarChart）。
 * values 为 0-100，与 labels 一一对应。
 */
export function RadarChart({
  labels,
  values,
  size = 260,
  color = PRIMARY_COLOR,
}: {
  labels: string[]
  values: number[]
  size?: number
  color?: string
}) {
  const data = labels.map((label, i) => ({ label, value: values[i] }))
  return (
    <ResponsiveContainer width="100%" height={size}>
      <ReRadarChart data={data} outerRadius="72%">
        <PolarGrid stroke={GRID_COLOR} />
        <PolarAngleAxis dataKey="label" tick={TICK_PROPS} />
        <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
        <Radar
          dataKey="value"
          stroke={color}
          fill={color}
          fillOpacity={0.18}
          strokeWidth={2}
        />
        <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => [`${v} 分`]} />
      </ReRadarChart>
    </ResponsiveContainer>
  )
}
