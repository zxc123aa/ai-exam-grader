import type {
  CornerEditor,
  CornerEditorOptions,
  CornerPoints,
  DetectionOptions,
  ScannerResult,
} from "scanic"
import { type ExamDocumentPublic, OpenAPI } from "@/client"

export type { CornerEditor, CornerPoints } from "scanic"

export type NormalizedPoint = {
  x: number
  y: number
}

export type NormalizedPageQuad = {
  label?: string
  points: [NormalizedPoint, NormalizedPoint, NormalizedPoint, NormalizedPoint]
}

export type DocumentDetectionResult = {
  success: boolean
  message: string
  confidence: number | null
  pages: NormalizedPageQuad[]
  raw: ScannerResult
}

export type DocumentQuadPreviewPage = {
  pageNumber: number
  name: string
  width: number
  height: number
  imageUrl: string
  orientation?: {
    rotation?: number
    status?: string
    reason?: string
    elapsed_ms?: number
    model_elapsed_ms?: number
    model?: string
  }
}

export type DocumentQuadPreviewResult = {
  quality: number
  status: string
  pageCount: number
  pages: DocumentQuadPreviewPage[]
  metadata?: Record<string, unknown>
}

type ImageSource = Blob | File | string

function authHeaders(extra?: HeadersInit) {
  const token = localStorage.getItem("access_token")
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extra,
  }
}

function clamp01(value: number) {
  return Math.max(0, Math.min(1, value))
}

export function cornersToNormalizedPageQuad(
  corners: CornerPoints,
  image: HTMLImageElement,
  label = "single",
): NormalizedPageQuad {
  const width = Math.max(1, image.naturalWidth || image.width)
  const height = Math.max(1, image.naturalHeight || image.height)
  return {
    label,
    points: [
      corners.topLeft,
      corners.topRight,
      corners.bottomRight,
      corners.bottomLeft,
    ].map((point) => ({
      x: clamp01(point.x / width),
      y: clamp01(point.y / height),
    })) as NormalizedPageQuad["points"],
  }
}

export function pageQuadToCorners(
  page: NormalizedPageQuad,
  image: HTMLImageElement,
): CornerPoints {
  const width = Math.max(1, image.naturalWidth || image.width)
  const height = Math.max(1, image.naturalHeight || image.height)
  const [topLeft, topRight, bottomRight, bottomLeft] = page.points
  return {
    topLeft: { x: topLeft.x * width, y: topLeft.y * height },
    topRight: { x: topRight.x * width, y: topRight.y * height },
    bottomRight: { x: bottomRight.x * width, y: bottomRight.y * height },
    bottomLeft: { x: bottomLeft.x * width, y: bottomLeft.y * height },
  }
}

export async function loadImageElement(source: ImageSource) {
  const objectUrl =
    typeof source === "string" ? null : URL.createObjectURL(source)
  const url = typeof source === "string" ? source : objectUrl!
  try {
    const image = new Image()
    image.decoding = "async"
    image.src = url
    await image.decode()
    return image
  } finally {
    if (objectUrl) URL.revokeObjectURL(objectUrl)
  }
}

export async function detectDocumentWithScanic(
  image: HTMLImageElement,
  options: DetectionOptions = {},
): Promise<DocumentDetectionResult> {
  const { scanDocument } = await import("scanic")
  const result = await scanDocument(image, {
    detector: "classical",
    maxProcessingDimension: 1800,
    minDetectionConfidence: 0.45,
    enableDetectionCascade: true,
    ...options,
  })
  const page =
    result.success && result.corners
      ? [cornersToNormalizedPageQuad(result.corners, image)]
      : []
  return {
    success: result.success,
    message: result.message,
    confidence:
      typeof result.confidence === "number"
        ? result.confidence
        : typeof result.score === "number"
          ? result.score
          : null,
    pages: page,
    raw: result,
  }
}

export async function createDocumentCornerEditor(
  options: CornerEditorOptions,
): Promise<CornerEditor> {
  const { createCornerEditor } = await import("scanic")
  const { magnifier, nudges, toolbar, theme, ...restOptions } = options
  return createCornerEditor({
    ...restOptions,
    magnifier: {
      enabled: true,
      zoom: 2,
      size: 120,
      ...(magnifier ?? {}),
    },
    nudges: {
      enabled: true,
      steps: [1, 5, 10],
      ...(nudges ?? {}),
    },
    toolbar: {
      enabled: true,
      ...(toolbar ?? {}),
      labels: {
        reset: "重置",
        cancel: "取消",
        apply: "确认四角",
        ...(toolbar?.labels ?? {}),
      },
    },
    theme: {
      accent: "#2563eb",
      edgeColor: "#2563eb",
      mask: "rgba(15, 23, 42, 0.45)",
      ...(theme ?? {}),
    },
  })
}

export async function fetchExamDocumentSourceImage(
  examId: string,
  documentId: string,
) {
  const response = await fetch(
    `${OpenAPI.BASE || ""}/api/v1/exams/${examId}/files/${documentId}/source-image`,
    { headers: authHeaders() },
  )
  if (!response.ok) throw new Error(await response.text())
  return response.blob()
}

export async function preprocessExamDocumentWithQuads({
  examId,
  documentId,
  pages,
  detector = "scanic_classical",
  marginMode = "conservative",
}: {
  examId: string
  documentId: string
  pages: NormalizedPageQuad[]
  detector?: string
  marginMode?: "conservative" | "minimal"
}): Promise<ExamDocumentPublic> {
  const response = await fetch(
    `${OpenAPI.BASE || ""}/api/v1/exams/${examId}/files/${documentId}/preprocess-with-quads`,
    {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        detector,
        margin_mode: marginMode,
        pages: pages.map((page) => ({
          label: page.label,
          points: page.points,
        })),
      }),
    },
  )
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}

export async function autoRectifyExamDocument({
  examId,
  documentId,
}: {
  examId: string
  documentId: string
}): Promise<ExamDocumentPublic> {
  const response = await fetch(
    `${OpenAPI.BASE || ""}/api/v1/exams/${examId}/files/${documentId}/auto-rectify`,
    {
      method: "POST",
      headers: authHeaders(),
    },
  )
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}

export async function autoRectifyExamDocuments({
  examId,
}: {
  examId: string
}): Promise<{ data: ExamDocumentPublic[]; count: number }> {
  const response = await fetch(
    `${OpenAPI.BASE || ""}/api/v1/exams/${examId}/files/auto-rectify`,
    {
      method: "POST",
      headers: authHeaders(),
    },
  )
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}

export async function previewExamDocumentWithQuads({
  examId,
  documentId,
  pages,
  detector = "scanic_classical",
  marginMode = "conservative",
}: {
  examId: string
  documentId: string
  pages: NormalizedPageQuad[]
  detector?: string
  marginMode?: "conservative" | "minimal"
}): Promise<DocumentQuadPreviewResult> {
  const response = await fetch(
    `${OpenAPI.BASE || ""}/api/v1/exams/${examId}/files/${documentId}/preview-with-quads`,
    {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        detector,
        margin_mode: marginMode,
        pages: pages.map((page) => ({
          label: page.label,
          points: page.points,
        })),
      }),
    },
  )
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}
