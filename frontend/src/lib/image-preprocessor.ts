/**
 * Pure-math image preprocessing utilities (no OpenCV dependency).
 *
 * These functions mirror the non-OpenCV parts of
 * backend/app/services/exam_photo_preprocessing.py and scan_preprocessing.py.
 * They can run on the main thread without waiting for OpenCV.js to load.
 */

export interface Point {
  x: number
  y: number
}

export type Quad = [Point, Point, Point, Point]

/**
 * Order 4 corner points as: top-left, top-right, bottom-right, bottom-left.
 * Exact mirror of exam_photo_preprocessing.py:order_points().
 */
export function orderPoints(points: Quad): Quad {
  const pts = points.map((p) => [p.x, p.y] as [number, number])
  const summed = pts.map(([x, y]) => x + y)
  const diff = pts.map(([x, y]) => y - x)

  const tlIdx = argMin(summed)
  const brIdx = argMax(summed)
  const trIdx = argMin(diff)
  const blIdx = argMax(diff)

  return [
    { x: pts[tlIdx][0], y: pts[tlIdx][1] },
    { x: pts[trIdx][0], y: pts[trIdx][1] },
    { x: pts[brIdx][0], y: pts[brIdx][1] },
    { x: pts[blIdx][0], y: pts[blIdx][1] },
  ]
}

function argMin(arr: number[]): number {
  let minIdx = 0
  for (let i = 1; i < arr.length; i++) {
    if (arr[i] < arr[minIdx]) minIdx = i
  }
  return minIdx
}

function argMax(arr: number[]): number {
  let maxIdx = 0
  for (let i = 1; i < arr.length; i++) {
    if (arr[i] > arr[maxIdx]) maxIdx = i
  }
  return maxIdx
}

/**
 * Expand page quad corners with margin for safe perspective correction.
 * Exact mirror of exam_photo_preprocessing.py:expand_page_quad().
 *
 * Uses the same margin ratios as the server:
 * - `safe`: 6% vertical, 6% outer, 1.5% inner
 * - `minimal`: 0.4% vertical, 0.4% outer/inner
 * - `conservative` (default): 4.5% vertical, 4.5% outer, 0.8% inner
 */
export function expandPageQuad(
  quad: Quad,
  imageWidth: number,
  imageHeight: number,
  opts: {
    pageIndex?: number
    pageCount?: number
    splitAxis?: "horizontal" | "vertical"
    marginMode?: "conservative" | "minimal" | "safe"
  } = {},
): Quad {
  const {
    pageIndex = 0,
    pageCount = 1,
    splitAxis = "horizontal",
    marginMode = "conservative",
  } = opts

  let verticalMargin: number
  let outerMargin: number
  let innerMargin: number

  if (marginMode === "minimal") {
    verticalMargin = Math.max(2.0, imageHeight * 0.004)
    outerMargin = Math.max(2.0, imageWidth * 0.004)
    innerMargin = Math.max(4.0, imageWidth * 0.004)
  } else if (marginMode === "safe") {
    verticalMargin = Math.max(16.0, imageHeight * 0.06)
    outerMargin = Math.max(16.0, imageWidth * 0.06)
    innerMargin = Math.max(10.0, imageWidth * 0.015)
  } else {
    // conservative
    verticalMargin = Math.max(12.0, imageHeight * 0.045)
    outerMargin = Math.max(12.0, imageWidth * 0.045)
    innerMargin = Math.max(8.0, imageWidth * 0.008)
  }

  const ordered = orderPoints(quad)
  const tl = { x: ordered[0].x, y: ordered[0].y }
  const tr = { x: ordered[1].x, y: ordered[1].y }
  const br = { x: ordered[2].x, y: ordered[2].y }
  const bl = { x: ordered[3].x, y: ordered[3].y }

  // Expand top
  tl.y -= verticalMargin
  tr.y -= verticalMargin
  // Expand bottom
  br.y += verticalMargin
  bl.y += verticalMargin

  if (pageCount === 1) {
    tl.x -= outerMargin
    bl.x -= outerMargin
    tr.x += outerMargin
    br.x += outerMargin
  } else if (splitAxis === "vertical" && pageIndex === 0) {
    tl.y -= outerMargin
    tr.y -= outerMargin
    br.y += innerMargin
    bl.y += innerMargin
    tl.x -= outerMargin
    bl.x -= outerMargin
    tr.x += outerMargin
    br.x += outerMargin
  } else if (splitAxis === "vertical") {
    tl.y -= innerMargin
    tr.y -= innerMargin
    br.y += outerMargin
    bl.y += outerMargin
    tl.x -= outerMargin
    bl.x -= outerMargin
    tr.x += outerMargin
    br.x += outerMargin
  } else if (pageIndex === 0) {
    tl.x -= outerMargin
    bl.x -= outerMargin
    tr.x += innerMargin
    br.x += innerMargin
  } else {
    tl.x -= innerMargin
    bl.x -= innerMargin
    tr.x += outerMargin
    br.x += outerMargin
  }

  // Clip to image bounds
  const clamp = (v: number, lo: number, hi: number) =>
    Math.max(lo, Math.min(hi, v))
  return [
    { x: clamp(tl.x, 0, imageWidth - 1), y: clamp(tl.y, 0, imageHeight - 1) },
    { x: clamp(tr.x, 0, imageWidth - 1), y: clamp(tr.y, 0, imageHeight - 1) },
    { x: clamp(br.x, 0, imageWidth - 1), y: clamp(br.y, 0, imageHeight - 1) },
    { x: clamp(bl.x, 0, imageWidth - 1), y: clamp(bl.y, 0, imageHeight - 1) },
  ]
}

/**
 * Convert normalized page quads (0-1 coordinates) to pixel coordinates.
 * Used to convert scanic output to the format the worker expects.
 */
export function normalizedQuadsToPixels(
  pages: Array<{
    points: [Point, Point, Point, Point]
    label?: string
  }>,
  imageWidth: number,
  imageHeight: number,
): Array<{
  quad: Quad
  label?: string
}> {
  return pages.map((page) => ({
    label: page.label,
    quad: page.points.map((p) => ({
      x: p.x * imageWidth,
      y: p.y * imageHeight,
    })) as Quad,
  }))
}

/**
 * Clamp a value to [0, 1].
 */
export function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value))
}

/**
 * Infer the split axis from a set of page quads.
 * Exact mirror of exam_photo_preprocessing.py:infer_manual_split_axis().
 */
export function inferSplitAxis(quads: Quad[]): {
  splitAxis: "horizontal" | "vertical" | "single"
  orderedQuads: Quad[]
} {
  if (quads.length <= 1) {
    return { splitAxis: "single", orderedQuads: [...quads] }
  }

  const centers = quads.map((quad) => {
    const cx = quad.reduce((s, p) => s + p.x, 0) / 4
    const cy = quad.reduce((s, p) => s + p.y, 0) / 4
    return { cx, cy, quad }
  })

  const xs = centers.map((c) => c.cx)
  const ys = centers.map((c) => c.cy)
  const xSpan = Math.max(...xs) - Math.min(...xs)
  const ySpan = Math.max(...ys) - Math.min(...ys)

  const splitAxis: "horizontal" | "vertical" =
    xSpan >= ySpan ? "horizontal" : "vertical"

  const ordered = centers
    .sort((a, b) => (splitAxis === "horizontal" ? a.cx - b.cx : a.cy - b.cy))
    .map((c) => c.quad)

  return { splitAxis, orderedQuads: ordered }
}
