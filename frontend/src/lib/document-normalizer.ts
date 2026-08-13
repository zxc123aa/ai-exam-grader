import type {
  CornerEditor,
  CornerEditorOptions,
  CornerPoints,
  DetectionOptions,
  ScannerResult,
} from "scanic"
import { type ExamDocumentPublic, OpenAPI } from "@/client"
import {
  inferSplitAxis,
  normalizedQuadsToPixels,
  type Quad,
} from "@/lib/image-preprocessor"
import {
  isPreprocessingAvailable,
  preprocessWithQuads,
} from "@/lib/opencv/loader"
import type {
  PageQuad,
  PreprocessedPage,
  PreprocessOptions,
} from "@/lib/opencv/types"

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

/** Result of client-side preprocessing */
export type ClientPreprocessResult = {
  success: boolean
  pages: Array<{
    name: string
    blob: Blob
    width: number
    height: number
    sharpness: number
    sourceQuad?: [number, number][]
  }>
  metadata: Record<string, unknown>
  /** If false, client preprocessing failed — use server fallback */
  clientProcessed: boolean
}

/** Status of the client preprocessing subsystem */
export type PreprocessingAvailability = {
  supported: boolean
  reason?: string
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

// ---- Client-side preprocessing ----------------------------------------------

/**
 * Get the pixel dimensions of an image from a Blob without loading it fully.
 */
async function getImageDimensions(
  blob: Blob,
): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob)
    const img = new Image()
    img.onload = () => {
      URL.revokeObjectURL(url)
      resolve({ width: img.naturalWidth, height: img.naturalHeight })
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error("Failed to decode image for dimension detection"))
    }
    img.src = url
  })
}

/**
 * Check whether client-side preprocessing can be used.
 *
 * Returns { supported: true } if the browser supports all required APIs
 * (Web Workers, OffscreenCanvas or canvas, etc.) and the worker can be created.
 */
export function checkPreprocessingAvailability(): PreprocessingAvailability {
  if (typeof Worker === "undefined") {
    return { supported: false, reason: "Web Workers not available" }
  }
  return { supported: true }
}

/**
 * Preprocess an exam photo entirely on the client using OpenCV.js (Web Worker).
 *
 * This mirrors the server's `preprocess_exam_photo_with_page_quads()` pipeline:
 * expand quads → perspective warp → CLAHE enhance → fine deskew.
 *
 * Orientation normalization (Gemini Vision) and OCR remain server-side.
 *
 * @param imageBlob - The original exam photo as a Blob/File
 * @param pages - Normalized page quads (0-1 coordinates) from scanic or manual input
 * @param options - Preprocessing options
 * @returns Preprocessed pages as Blobs + metadata.
 *          On failure, returns { clientProcessed: false } — caller should fall
 *          back to server-side preprocessing.
 */
export async function clientPreprocessWithQuads(
  imageBlob: Blob,
  pages: NormalizedPageQuad[],
  options: PreprocessOptions = {},
): Promise<ClientPreprocessResult> {
  try {
    // 1. Get image dimensions
    const { width: imageWidth, height: imageHeight } =
      await getImageDimensions(imageBlob)

    // 2. Read image blob as ArrayBuffer
    const imageBuffer = await imageBlob.arrayBuffer()

    // 3. Convert normalized quads (0-1) to pixel quads
    const pixelQuads = normalizedQuadsToPixels(
      pages.map((p) => ({ points: p.points, label: p.label })),
      imageWidth,
      imageHeight,
    )

    // 4. Infer split axis
    const quads: Quad[] = pixelQuads.map((pq) => pq.quad)
    const { splitAxis, orderedQuads } = inferSplitAxis(quads)

    // 5. Convert to worker format (array of [x,y] tuples)
    const workerQuads: PageQuad[] = orderedQuads.map((q) =>
      q.map((p) => [p.x, p.y] as [number, number]),
    ) as PageQuad[]

    // 6. Run preprocessing in worker (the worker has its own 30s timeout)
    const effectiveSplitAxis = splitAxis === "single" ? undefined : splitAxis
    const result = await preprocessWithQuads(imageBuffer, workerQuads, {
      ...options,
      splitAxis: effectiveSplitAxis,
    })

    // 7. Convert result pages to Blobs
    const processedPages = result.pages.map((page: PreprocessedPage) => ({
      name: page.name,
      blob: new Blob([page.buffer], { type: "image/jpeg" }),
      width: page.width,
      height: page.height,
      sharpness: page.sharpness,
      sourceQuad: page.sourceQuad as [number, number][] | undefined,
    }))

    return {
      success: true,
      pages: processedPages,
      metadata: result.metadata,
      clientProcessed: true,
    }
  } catch (err) {
    console.warn(
      "[clientPreprocessWithQuads] Client preprocessing failed, falling back to server:",
      err,
    )
    return {
      success: false,
      pages: [],
      metadata: { error: String(err) },
      clientProcessed: false,
    }
  }
}

/**
 * Check if the client preprocessing worker is currently ready.
 * Use this to decide whether to attempt client-side preprocessing.
 *
 * Note: the first call to `clientPreprocessWithQuads()` will initialize the
 * worker if needed, but there may be a slight delay for OpenCV.js loading.
 */
export function isClientPreprocessingReady(): boolean {
  return isPreprocessingAvailable()
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

export async function uploadClientPreprocessedPages({
  examId,
  documentId,
  pages,
  detector = "client_opencvjs",
  marginMode = "conservative",
}: {
  examId: string
  documentId: string
  pages: Array<{
    name: string
    blob: Blob
    width: number
    height: number
    sourceQuad?: [number, number][]
  }>
  detector?: string
  marginMode?: "conservative" | "minimal" | "safe"
}): Promise<ExamDocumentPublic> {
  // Encode each page blob as base64
  const encodedPages = await Promise.all(
    pages.map(async (page) => {
      const buffer = await page.blob.arrayBuffer()
      const bytes = new Uint8Array(buffer)
      let binary = ""
      for (let i = 0; i < bytes.length; i++) {
        binary += String.fromCharCode(bytes[i])
      }
      const base64 = btoa(binary)
      return {
        name: page.name,
        image_base64: base64,
        width: page.width,
        height: page.height,
        source_quad: page.sourceQuad ?? null,
      }
    }),
  )

  const response = await fetch(
    `${OpenAPI.BASE || ""}/api/v1/exams/${examId}/files/${documentId}/upload-preprocessed`,
    {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        detector,
        margin_mode: marginMode,
        pages: encodedPages,
      }),
    },
  )
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}
