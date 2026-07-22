export type PaginationRangeItem = number | "ellipsis"

/**
 * 生成数字页码序列：始终显示首尾页和当前页 ±1，中间缺口用 "ellipsis" 折叠。
 * current 为 1 起始的当前页码，total 为总页数。
 */
export function getPaginationRange(
  current: number,
  total: number,
): PaginationRangeItem[] {
  if (total <= 0) return []
  const clamped = Math.min(Math.max(current, 1), total)
  const pages = [...new Set([1, total, clamped - 1, clamped, clamped + 1])]
    .filter((page) => page >= 1 && page <= total)
    .sort((a, b) => a - b)

  const range: PaginationRangeItem[] = []
  let previous = 0
  for (const page of pages) {
    if (previous > 0 && page - previous > 1) {
      range.push("ellipsis")
    }
    range.push(page)
    previous = page
  }
  return range
}
