import { cn } from "@/lib/utils"

/**
 * 知识点 × 维度热力图（对齐原型 heatmapChart）。
 * 纯 CSS grid 实现，不依赖 recharts；
 * 颜色为主色按值映射透明度，格内显示数值，hover 出 title 提示。
 */
export interface HeatmapRow {
  /** 行名（知识点） */
  kp: string
  /** 0-100，与 cols 一一对应 */
  values: number[]
}

export function Heatmap({
  rows,
  cols,
  className,
}: {
  rows: HeatmapRow[]
  cols: string[]
  className?: string
}) {
  return (
    <div className={cn("overflow-x-auto", className)}>
      <div
        className="grid min-w-max gap-1.5"
        style={{
          gridTemplateColumns: `minmax(96px, auto) repeat(${cols.length}, minmax(72px, 1fr))`,
        }}
      >
        {/* 表头 */}
        <span />
        {cols.map((c) => (
          <span key={c} className="px-2 py-1 text-center font-semibold text-xs">
            {c}
          </span>
        ))}
        {/* 数据行 */}
        {rows.map((row) => (
          <HeatmapRowCells key={row.kp} row={row} cols={cols} />
        ))}
      </div>
    </div>
  )
}

function HeatmapRowCells({ row, cols }: { row: HeatmapRow; cols: string[] }) {
  return (
    <>
      <span className="flex items-center justify-end pr-2 text-muted-foreground text-xs">
        {row.kp}
      </span>
      {row.values.map((v, ci) => {
        const alpha = 0.12 + (Math.min(100, Math.max(0, v)) / 100) * 0.78
        return (
          <span
            key={cols[ci]}
            title={`${row.kp} · ${cols[ci]}：${v} 分`}
            className={cn(
              "flex h-10 items-center justify-center rounded-lg font-semibold text-xs tabular-nums transition-transform hover:scale-[1.03]",
              v > 55 ? "text-white" : "text-foreground",
            )}
            style={{
              backgroundColor: `rgba(46, 91, 255, ${alpha.toFixed(2)})`,
            }}
          >
            {v}
          </span>
        )
      })}
    </>
  )
}
