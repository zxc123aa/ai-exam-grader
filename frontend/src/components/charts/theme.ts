/**
 * 图表统一配置：颜色取自全局 CSS 变量（浅色/深色自动切换）。
 * recharts 会把这些字符串直接写入 SVG 属性，var() 由浏览器解析。
 */

/** 序列默认色板，依次取 chart-1..5 */
export const CHART_PALETTE = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
] as const

/** 网格线颜色 */
export const GRID_COLOR = "var(--border)"
/** 坐标轴刻度文字颜色 */
export const TICK_COLOR = "var(--muted-foreground)"
/** 主色（单系列图表默认） */
export const PRIMARY_COLOR = "var(--chart-1)"
/** 低分项红色 */
export const DANGER_COLOR = "var(--destructive)"

/** Tooltip 容器样式：跟随卡片配色，深浅色通用 */
export const TOOLTIP_STYLE: React.CSSProperties = {
  backgroundColor: "var(--card)",
  border: "1px solid var(--border)",
  borderRadius: 12,
  fontSize: 12,
  color: "var(--card-foreground)",
  boxShadow: "var(--shadow-card-lg)",
}

/** 坐标轴刻度通用属性 */
export const TICK_PROPS = { fontSize: 11, fill: TICK_COLOR } as const
