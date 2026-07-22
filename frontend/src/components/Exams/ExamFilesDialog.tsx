import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  ArrowDown,
  ArrowUp,
  FileText,
  FileUp,
  ImageIcon,
  Loader2,
  ScanLine,
  Trash2,
} from "lucide-react"
import { type ReactNode, useEffect, useRef, useState } from "react"

import {
  type ExamDocumentPublic,
  type ExamDocumentsPublic,
  type ExamDocumentType,
  type ExamPublic,
  ExamsService,
  OpenAPI,
} from "@/client"
import { ConfirmDialog } from "@/components/Common/ConfirmDialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import {
  autoRectifyExamDocument,
  autoRectifyExamDocuments,
  type CornerEditor,
  type CornerPoints,
  cornersToNormalizedPageQuad,
  createDocumentCornerEditor,
  detectDocumentWithScanic,
  fetchExamDocumentSourceImage,
  type NormalizedPageQuad,
  pageQuadToCorners,
  preprocessExamDocumentWithQuads,
  previewExamDocumentWithQuads,
} from "@/lib/document-normalizer"
import { workflowApi } from "@/lib/workflow-api"
import { handleError } from "@/utils"

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function formatDocumentType(documentType?: ExamDocumentType) {
  if (documentType === "answer_key") return "答案卷"
  return "模板试卷"
}

type ScanWarning = {
  code: string
  severity: string
  message: string
}

function readScanWarnings(document: ExamDocumentPublic): ScanWarning[] {
  const metadata = document.preprocessing_metadata
  if (!metadata || typeof metadata !== "object") return []
  const quality = metadata.quality
  if (!quality || typeof quality !== "object") return []
  const warnings = (quality as Record<string, unknown>).warnings
  if (!Array.isArray(warnings)) return []
  return warnings
    .filter(
      (item): item is ScanWarning =>
        typeof item === "object" &&
        item !== null &&
        typeof (item as Record<string, unknown>).message === "string",
    )
    .filter(
      (warning, index, items) =>
        items.findIndex((item) => item.code === warning.code) === index,
    )
}

function formatScanWarning(warning: ScanWarning) {
  const labels: Record<string, string> = {
    low_sharpness: "图片清晰度偏低",
    low_gutter_confidence: "双页中缝置信度偏低",
    split_half_page_fallback: "使用了左右页回退分割",
    content_near_top_edge: "顶部内容靠近裁切边缘",
    content_near_bottom_edge: "底部内容靠近裁切边缘",
    content_near_left_edge: "左侧内容靠近裁切边缘",
    content_near_right_edge: "右侧内容靠近裁切边缘",
    vision_page_polygon_rejected: "Gemini 页面边界未通过几何校验",
    vision_page_polygon_failed: "Gemini 页面边界检测失败",
    doc_unwarping_unavailable: "文档方向/曲面展开服务暂不可用",
    doc_unwarping_quality_rejected: "曲面展开结果退化，已保留透视校正页",
  }
  return labels[warning.code] || warning.message
}

function readScanTotalMs(document: ExamDocumentPublic) {
  const metadata = document.preprocessing_metadata
  if (!metadata || typeof metadata !== "object") return null
  const debug = metadata.debug
  if (!debug || typeof debug !== "object") return null
  const timings = (debug as Record<string, unknown>).timings
  if (!timings || typeof timings !== "object") return null
  const total = (timings as Record<string, unknown>).total_ms
  return typeof total === "number" ? total : null
}

type PreprocessingPreviewKind = "detected_overlay" | "corrected_spread"

function hasPreprocessingPreview(
  document: ExamDocumentPublic,
  kind: PreprocessingPreviewKind,
) {
  const metadata = document.preprocessing_metadata
  if (!metadata || typeof metadata !== "object") return false
  const previewFiles = metadata.preview_files
  if (!previewFiles || typeof previewFiles !== "object") return false
  const preview = (previewFiles as Record<string, unknown>)[kind]
  if (!preview || typeof preview !== "object") return false
  return typeof (preview as Record<string, unknown>).stored_file_id === "string"
}

function formatPreprocessingStatus(status?: string) {
  const labels: Record<string, string> = {
    ready: "扫描通过",
    review: "需要复核",
    failed: "扫描失败",
    not_required: "原始文件",
  }
  return labels[status || "not_required"] || status || "原始文件"
}

function PreprocessingPreview({
  examId,
  document,
}: {
  examId: string
  document: ExamDocumentPublic
}) {
  const previewKinds: {
    kind: PreprocessingPreviewKind
    label: string
    description: string
  }[] = [
    {
      kind: "detected_overlay",
      label: "原图检测框",
      description: "看 Gemini/OpenCV 找到的纸面边界",
    },
    {
      kind: "corrected_spread",
      label: "校正后预览",
      description: "看真正应用到 PDF 的摆正结果",
    },
  ]
  const availableKinds = previewKinds.filter((item) =>
    hasPreprocessingPreview(document, item.kind),
  )
  const [urls, setUrls] = useState<Record<string, string | null>>({})
  const [isLoading, setIsLoading] = useState(availableKinds.length > 0)

  useEffect(() => {
    let cancelled = false
    const objectUrls: string[] = []
    if (availableKinds.length === 0) {
      setUrls({})
      setIsLoading(false)
      return () => undefined
    }
    setIsLoading(true)
    Promise.all(
      availableKinds.map(async ({ kind }) => {
        const response = await fetch(
          `${OpenAPI.BASE || ""}/api/v1/exams/${examId}/files/${document.id}/preprocessing-preview/${kind}`,
          { headers: authHeaders() },
        )
        if (!response.ok) return [kind, null] as const
        const url = URL.createObjectURL(await response.blob())
        objectUrls.push(url)
        return [kind, url] as const
      }),
    )
      .then((entries) => {
        if (!cancelled) setUrls(Object.fromEntries(entries))
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
      objectUrls.forEach((url) => URL.revokeObjectURL(url))
    }
  }, [document.id, examId, availableKinds.map, availableKinds.length])

  if (availableKinds.length === 0) return null

  return (
    <div className="ml-11 grid gap-2 border-t pt-2">
      <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <ImageIcon className="size-3.5" />
        预处理质检
      </div>
      {isLoading ? (
        <div className="text-xs text-muted-foreground">正在加载预处理预览…</div>
      ) : (
        <div className="grid gap-2 xl:grid-cols-2">
          {availableKinds.map(({ kind, label, description }) => {
            const url = urls[kind]
            return (
              <div key={kind} className="overflow-hidden rounded-md border">
                <div className="border-b bg-muted/30 px-2 py-1">
                  <div className="text-xs font-medium">{label}</div>
                  <div className="text-[11px] text-muted-foreground">
                    {description}
                  </div>
                </div>
                {url ? (
                  <a href={url} target="_blank" rel="noreferrer">
                    <img
                      src={url}
                      alt={label}
                      className="block max-h-72 w-full bg-muted/20 object-contain"
                    />
                  </a>
                ) : (
                  <div className="flex h-24 items-center justify-center text-xs text-destructive">
                    预览加载失败
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function formatScanStrategy(document: ExamDocumentPublic) {
  const metadata = document.preprocessing_metadata
  if (!metadata || typeof metadata !== "object") return null
  const split = metadata.split
  if (!split || typeof split !== "object") return null
  const strategy = (split as Record<string, unknown>).strategy
  const labels: Record<string, string> = {
    single_page: "单页",
    vision_single_page: "视觉单页边界",
    vision_page_polygons: "视觉双页边界",
    detected_gutter: "中缝检测",
    center_fallback: "中心回退",
    split_half_page_fallback: "左右页回退",
    scan_service_single_page: "文档展开",
  }
  return typeof strategy === "string" ? labels[strategy] || strategy : null
}

function moveItem<T>(items: T[], index: number, offset: -1 | 1) {
  const nextIndex = index + offset
  if (nextIndex < 0 || nextIndex >= items.length) return items
  const next = [...items]
  ;[next[index], next[nextIndex]] = [next[nextIndex], next[index]]
  return next
}

function authHeaders(extra?: HeadersInit) {
  const token = localStorage.getItem("access_token")
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extra,
  }
}

function SplitPagePreview({
  examId,
  documentId,
  pageCount,
}: {
  examId: string
  documentId: string
  pageCount: number
}) {
  const [urls, setUrls] = useState<(string | null)[]>([])
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const objectUrls: string[] = []
    setIsLoading(true)
    Promise.all(
      Array.from({ length: pageCount }, async (_, index) => {
        const response = await fetch(
          `${OpenAPI.BASE || ""}/api/v1/exams/${examId}/files/${documentId}/pages/${index + 1}/image`,
          { headers: authHeaders() },
        )
        if (!response.ok) return null
        const url = URL.createObjectURL(await response.blob())
        objectUrls.push(url)
        return url
      }),
    )
      .then((nextUrls) => {
        if (!cancelled) setUrls(nextUrls)
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
      objectUrls.forEach((url) => {
        URL.revokeObjectURL(url)
      })
    }
  }, [documentId, examId, pageCount])

  return (
    <div className="ml-11 grid gap-2 border-t pt-2">
      <div className="text-xs font-medium text-muted-foreground">分割结果</div>
      {isLoading ? (
        <div className="text-xs text-muted-foreground">正在加载切分页图…</div>
      ) : (
        <div className="grid grid-cols-2 gap-2 xl:grid-cols-3">
          {urls.map((url, index) => (
            <div
              key={`${documentId}-${index}`}
              className="relative overflow-hidden rounded-md border bg-muted/20"
            >
              {url ? (
                <img
                  src={url}
                  alt={`分割第 ${index + 1} 页`}
                  className="block max-h-56 w-full object-contain"
                />
              ) : (
                <div className="flex h-24 items-center justify-center text-xs text-destructive">
                  页面加载失败
                </div>
              )}
              <span className="absolute bottom-1 left-1 rounded-sm bg-black/70 px-1.5 py-0.5 text-xs text-white">
                第 {index + 1} 页
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

type BrowserDetectorMode = "classical" | "ml"
type DetectorMode = "stable" | BrowserDetectorMode
type PageMode = "single" | "spread"

function getErrorMessage(error: unknown) {
  if (error instanceof Error) return error.message
  return String(error)
}

function buildInsetPageQuad(inset = 0.035): NormalizedPageQuad {
  return {
    label: "manual",
    points: [
      { x: inset, y: inset },
      { x: 1 - inset, y: inset },
      { x: 1 - inset, y: 1 - inset },
      { x: inset, y: 1 - inset },
    ],
  }
}

function readStoredDetectedQuad(
  document: ExamDocumentPublic,
  image: HTMLImageElement,
): NormalizedPageQuad | null {
  const metadata = document.preprocessing_metadata
  if (!metadata || typeof metadata !== "object") return null
  const detectedQuad = (metadata as Record<string, unknown>).detected_quad
  if (!Array.isArray(detectedQuad) || detectedQuad.length !== 4) return null

  const width = Math.max(1, image.naturalWidth || image.width)
  const height = Math.max(1, image.naturalHeight || image.height)
  const points = detectedQuad.map((point) => {
    if (!Array.isArray(point) || point.length < 2) return null
    const [x, y] = point
    if (typeof x !== "number" || typeof y !== "number") return null
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null
    return {
      x: Math.max(0, Math.min(1, x / width)),
      y: Math.max(0, Math.min(1, y / height)),
    }
  })
  if (points.some((point) => point == null)) return null
  return {
    label: "stored_scan_engine_quad",
    points: points as NormalizedPageQuad["points"],
  }
}

function isLandscapeSpreadImage(image: HTMLImageElement) {
  const width = image.naturalWidth || image.width
  const height = image.naturalHeight || image.height
  return width >= height * 1.18
}

function pointBetween(
  a: { x: number; y: number },
  b: { x: number; y: number },
  ratio: number,
) {
  return {
    x: a.x + (b.x - a.x) * ratio,
    y: a.y + (b.y - a.y) * ratio,
  }
}

function splitSpreadCornersToPages(
  corners: CornerPoints,
  image: HTMLImageElement,
  gutterRatio = 0.5,
): NormalizedPageQuad[] {
  const widthTop = Math.hypot(
    corners.topRight.x - corners.topLeft.x,
    corners.topRight.y - corners.topLeft.y,
  )
  const widthBottom = Math.hypot(
    corners.bottomRight.x - corners.bottomLeft.x,
    corners.bottomRight.y - corners.bottomLeft.y,
  )
  const heightLeft = Math.hypot(
    corners.bottomLeft.x - corners.topLeft.x,
    corners.bottomLeft.y - corners.topLeft.y,
  )
  const heightRight = Math.hypot(
    corners.bottomRight.x - corners.topRight.x,
    corners.bottomRight.y - corners.topRight.y,
  )
  const horizontalSpread = widthTop + widthBottom >= heightLeft + heightRight
  if (horizontalSpread) {
    const topMid = pointBetween(corners.topLeft, corners.topRight, gutterRatio)
    const bottomMid = pointBetween(
      corners.bottomLeft,
      corners.bottomRight,
      gutterRatio,
    )
    return [
      cornersToNormalizedPageQuad(
        {
          topLeft: corners.topLeft,
          topRight: topMid,
          bottomRight: bottomMid,
          bottomLeft: corners.bottomLeft,
        },
        image,
        "left",
      ),
      cornersToNormalizedPageQuad(
        {
          topLeft: topMid,
          topRight: corners.topRight,
          bottomRight: corners.bottomRight,
          bottomLeft: bottomMid,
        },
        image,
        "right",
      ),
    ]
  }

  const leftMid = pointBetween(corners.topLeft, corners.bottomLeft, gutterRatio)
  const rightMid = pointBetween(
    corners.topRight,
    corners.bottomRight,
    gutterRatio,
  )
  return [
    cornersToNormalizedPageQuad(
      {
        topLeft: corners.topLeft,
        topRight: corners.topRight,
        bottomRight: rightMid,
        bottomLeft: leftMid,
      },
      image,
      "top",
    ),
    cornersToNormalizedPageQuad(
      {
        topLeft: leftMid,
        topRight: rightMid,
        bottomRight: corners.bottomRight,
        bottomLeft: corners.bottomLeft,
      },
      image,
      "bottom",
    ),
  ]
}

function canReviewDocumentCorners(document: ExamDocumentPublic) {
  const contentType = document.stored_file.content_type ?? ""
  return (
    contentType.startsWith("image/") ||
    Boolean(document.original_stored_file_id)
  )
}

export function DocumentCornerReviewDialog({
  examId,
  document,
  open,
  onOpenChange,
  onSaved,
}: {
  examId: string
  document: ExamDocumentPublic | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: (document: ExamDocumentPublic) => void
}) {
  const editorHostRef = useRef<HTMLDivElement | null>(null)
  const editorRef = useRef<CornerEditor | null>(null)
  const imageRef = useRef<HTMLImageElement | null>(null)
  const objectUrlRef = useRef<string | null>(null)
  const pageModeRef = useRef<PageMode>("single")
  const [detector, setDetector] = useState<DetectorMode>("classical")
  const [pageMode, setPageMode] = useState<PageMode>("single")
  const [status, setStatus] = useState<
    "idle" | "loading" | "detecting" | "ready" | "saving" | "failed"
  >("idle")
  const [message, setMessage] = useState("尚未检测")
  const [confidence, setConfidence] = useState<number | null>(null)
  const [imageSize, setImageSize] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [previewPages, setPreviewPages] = useState<
    {
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
    }[]
  >([])
  const [previewSummary, setPreviewSummary] = useState<string | null>(null)
  const [autoRectifying, setAutoRectifying] = useState(false)
  const { showSuccessToast, showErrorToast } = useCustomToast()

  function updatePageMode(nextPageMode: PageMode) {
    pageModeRef.current = nextPageMode
    setPageMode(nextPageMode)
    setPreviewPages([])
    setPreviewSummary(null)
  }

  function clearEditor() {
    editorRef.current?.destroy()
    editorRef.current = null
    if (editorHostRef.current) editorHostRef.current.innerHTML = ""
  }

  function clearObjectUrl() {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current)
      objectUrlRef.current = null
    }
  }

  async function saveCorners(
    corners: CornerPoints,
    image: HTMLImageElement,
    nextPageMode: PageMode,
  ) {
    if (!document) return
    setStatus("saving")
    setError(null)
    const pages =
      nextPageMode === "spread"
        ? splitSpreadCornersToPages(corners, image)
        : [cornersToNormalizedPageQuad(corners, image, "single")]
    try {
      const updatedDocument = await preprocessExamDocumentWithQuads({
        examId,
        documentId: document.id,
        detector: `scanic_${detector}_${nextPageMode}_manual`,
        marginMode: "minimal",
        pages,
      })
      onSaved(updatedDocument)
      onOpenChange(false)
    } catch (err) {
      const nextError = getErrorMessage(err)
      setError(nextError)
      showErrorToast(`四角校正保存失败：${nextError}`)
      setStatus("ready")
    }
  }

  async function previewCorners(
    corners: CornerPoints,
    image: HTMLImageElement,
    nextPageMode: PageMode,
  ) {
    if (!document) return
    setStatus("saving")
    setError(null)
    setPreviewSummary("正在生成校正预览…")
    const pages =
      nextPageMode === "spread"
        ? splitSpreadCornersToPages(corners, image)
        : [cornersToNormalizedPageQuad(corners, image, "single")]
    try {
      const result = await previewExamDocumentWithQuads({
        examId,
        documentId: document.id,
        detector: `scanic_${detector}_${nextPageMode}_manual`,
        marginMode: "minimal",
        pages,
      })
      setPreviewPages(result.pages)
      setPreviewSummary(
        `预览完成：${result.pageCount} 页 · 质量 ${Math.round(result.quality * 100)}% · ${result.status === "ready" ? "可直接保存" : "建议再复核"}`,
      )
      setStatus("ready")
    } catch (err) {
      const nextError = getErrorMessage(err)
      setError(nextError)
      setPreviewSummary(null)
      showErrorToast(`生成校正预览失败：${nextError}`)
      setStatus("ready")
    }
  }

  async function autoRectifyAndApply() {
    if (!document) return
    setAutoRectifying(true)
    setError(null)
    setMessage("正在自动摆正卷子并生成扫描页…")
    try {
      const updatedDocument = await autoRectifyExamDocument({
        examId,
        documentId: document.id,
      })
      onSaved(updatedDocument)
      showSuccessToast("自动摆正已应用到主画布")
      onOpenChange(false)
    } catch (err) {
      const nextError = getErrorMessage(err)
      setError(nextError)
      showErrorToast(`自动摆正失败：${nextError}`)
      setMessage("自动摆正失败，请尝试手动拖动四角后保存")
    } finally {
      setAutoRectifying(false)
    }
  }

  async function mountEditor(
    image: HTMLImageElement,
    page: NormalizedPageQuad,
    nextDetector: DetectorMode,
  ) {
    const container = editorHostRef.current
    if (!container) return
    clearEditor()
    editorRef.current = await createDocumentCornerEditor({
      container,
      image,
      corners: pageQuadToCorners(page, image),
      toolbar: {
        labels: {
          reset: "重置",
          cancel: "关闭",
          apply: "确认四角并保存",
        },
      },
      onConfirm: (corners) => {
        setDetector(nextDetector)
        void saveCorners(corners, image, pageModeRef.current)
      },
      onCancel: () => onOpenChange(false),
    })
  }

  async function detectAndMount(
    image: HTMLImageElement,
    nextDetector: BrowserDetectorMode,
  ) {
    setDetector(nextDetector)
    setStatus("detecting")
    setError(null)
    setMessage(
      nextDetector === "ml"
        ? "正在用 ML 角点检测器检测纸面边界…"
        : "正在用 classical 边缘检测器检测纸面边界…",
    )
    try {
      const detection = await detectDocumentWithScanic(image, {
        detector: nextDetector,
      })
      const page = detection.pages[0] ?? buildInsetPageQuad()
      setConfidence(detection.confidence)
      const autoPageMode = isLandscapeSpreadImage(image) ? "spread" : "single"
      updatePageMode(autoPageMode)
      setMessage(
        detection.success
          ? detection.message || "已检测到纸面四角，请复核后确认"
          : "自动检测未通过，已给出默认四角，请手动拖动修正",
      )
      await mountEditor(image, page, nextDetector)
      setStatus("ready")
    } catch (err) {
      const fallbackPage = buildInsetPageQuad()
      await mountEditor(image, fallbackPage, nextDetector)
      setConfidence(null)
      updatePageMode(isLandscapeSpreadImage(image) ? "spread" : "single")
      setMessage("检测器异常，已给出默认四角，请手动拖动修正")
      setError(getErrorMessage(err))
      setStatus("ready")
    }
  }

  async function loadSourceAndDetect(nextDetector: BrowserDetectorMode) {
    if (!document) return
    clearEditor()
    clearObjectUrl()
    imageRef.current = null
    setStatus("loading")
    setError(null)
    setConfidence(null)
    setImageSize(null)
    setPreviewPages([])
    setPreviewSummary(null)
    setMessage("正在读取原始图片…")
    try {
      const blob = await fetchExamDocumentSourceImage(examId, document.id)
      const objectUrl = URL.createObjectURL(blob)
      objectUrlRef.current = objectUrl
      const image = new Image()
      image.decoding = "async"
      image.src = objectUrl
      await image.decode()
      imageRef.current = image
      setImageSize(`${image.naturalWidth}×${image.naturalHeight}`)
      await detectAndMount(image, nextDetector)
    } catch (err) {
      const nextError = getErrorMessage(err)
      setStatus("failed")
      setMessage("原图读取或四角检测失败")
      setError(nextError)
      showErrorToast(`四角复核失败：${nextError}`)
    }
  }

  async function loadSourceAndUseStoredQuad() {
    if (!document) return
    clearEditor()
    clearObjectUrl()
    imageRef.current = null
    setDetector("stable")
    setStatus("loading")
    setError(null)
    setConfidence(null)
    setImageSize(null)
    setPreviewPages([])
    setPreviewSummary(null)
    setMessage("正在读取原图和后端稳定算法检测框…")
    try {
      const blob = await fetchExamDocumentSourceImage(examId, document.id)
      const objectUrl = URL.createObjectURL(blob)
      objectUrlRef.current = objectUrl
      const image = new Image()
      image.decoding = "async"
      image.src = objectUrl
      await image.decode()
      imageRef.current = image
      setImageSize(`${image.naturalWidth}×${image.naturalHeight}`)

      const storedPage = readStoredDetectedQuad(document, image)
      if (!storedPage) {
        await detectAndMount(image, "classical")
        return
      }

      setConfidence(document.preprocessing_quality ?? null)
      updatePageMode(isLandscapeSpreadImage(image) ? "spread" : "single")
      setMessage(
        "已加载后端稳定扫描算法的纸面边界；如四角仍不准，可手动拖动或使用备用四角检测。",
      )
      await mountEditor(image, storedPage, "stable")
      setStatus("ready")
    } catch (err) {
      const nextError = getErrorMessage(err)
      setStatus("failed")
      setMessage("原图读取或后端稳定算法检测框加载失败")
      setError(nextError)
      showErrorToast(`四角复核失败：${nextError}`)
    }
  }

  useEffect(() => {
    if (!open || !document) {
      clearEditor()
      clearObjectUrl()
      imageRef.current = null
      setStatus("idle")
      return
    }
    void loadSourceAndUseStoredQuad()
    return () => {
      clearEditor()
      clearObjectUrl()
      imageRef.current = null
    }
  }, [
    open,
    document?.id,
    document,
    loadSourceAndUseStoredQuad,
    clearObjectUrl,
    clearEditor,
  ])

  const isBusy =
    autoRectifying ||
    status === "loading" ||
    status === "detecting" ||
    status === "saving"

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle>复核纸面四角 / 重新扫描</DialogTitle>
          <DialogDescription>
            默认加载后端稳定扫描算法的纸面边界；如四角不准，直接拖动四个角点。备用四角检测只用于辅助修框，最终重新扫描走当前后端扫描引擎。
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border bg-muted/20 px-3 py-2 text-xs">
            <div className="min-w-0">
              <div className="truncate font-medium">
                {document?.stored_file.original_filename ?? "未选择文件"}
              </div>
              <div className="text-muted-foreground">
                {imageSize ? `原图尺寸 ${imageSize}` : "等待读取原图"}
                {confidence != null
                  ? ` · 检测置信度 ${Math.round(confidence * 100)}%`
                  : ""}
              </div>
            </div>
            <div className="flex gap-2">
              <Button
                type="button"
                variant={pageMode === "single" ? "default" : "outline"}
                size="sm"
                disabled={isBusy}
                onClick={() => updatePageMode("single")}
              >
                单页
              </Button>
              <Button
                type="button"
                variant={pageMode === "spread" ? "default" : "outline"}
                size="sm"
                disabled={isBusy}
                onClick={() => updatePageMode("spread")}
              >
                双页摊开
              </Button>
              <LoadingButton
                type="button"
                variant={detector === "classical" ? "default" : "outline"}
                size="sm"
                loading={isBusy && detector === "classical"}
                disabled={isBusy}
                onClick={() => void loadSourceAndDetect("classical")}
              >
                <ScanLine />
                备用传统四角
              </LoadingButton>
              <LoadingButton
                type="button"
                variant={detector === "ml" ? "default" : "outline"}
                size="sm"
                loading={isBusy && detector === "ml"}
                disabled={isBusy}
                onClick={() => void loadSourceAndDetect("ml")}
              >
                <ScanLine />
                备用 ML 四角
              </LoadingButton>
            </div>
          </div>

          <div className="rounded-md border px-3 py-2 text-xs text-muted-foreground">
            {message}
            {pageMode === "spread"
              ? " 当前按双页摊开处理：确认后会沿纸面中线生成两页。"
              : " 当前按单页处理：确认后只生成一页。"}
            {status === "saving" ? " 正在保存重新扫描结果…" : ""}
            {error ? (
              <div className="mt-1 text-destructive">{error}</div>
            ) : null}
          </div>

          <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_320px]">
            <div className="relative min-h-[62vh] overflow-hidden rounded-md border bg-slate-950/5">
              <div ref={editorHostRef} className="min-h-[62vh]" />
              {status === "loading" || status === "detecting" ? (
                <div className="absolute inset-0 flex items-center justify-center gap-2 bg-slate-950/5 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" />
                  {message}
                </div>
              ) : null}
            </div>
            <div className="grid content-start gap-3">
              <div className="rounded-md border p-3">
                <div className="mb-2 text-sm font-medium">校正预览</div>
                {previewSummary ? (
                  <div className="mb-3 rounded-md bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                    {previewSummary}
                  </div>
                ) : (
                  <div className="mb-3 rounded-md bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                    “自动摆正并应用”会直接调用后端当前扫描引擎；“生成预览”只预览当前四角手动校正效果。
                  </div>
                )}
                <div className="flex flex-wrap gap-2">
                  <LoadingButton
                    type="button"
                    size="sm"
                    loading={autoRectifying}
                    disabled={status === "loading" || status === "detecting"}
                    onClick={() => void autoRectifyAndApply()}
                  >
                    <ScanLine />
                    用稳定算法摆正并应用
                  </LoadingButton>
                  <LoadingButton
                    type="button"
                    variant="outline"
                    size="sm"
                    loading={status === "saving" && previewPages.length === 0}
                    disabled={status === "loading" || status === "detecting"}
                    onClick={() => {
                      if (!imageRef.current || !editorRef.current) return
                      void previewCorners(
                        editorRef.current.getCorners(),
                        imageRef.current,
                        pageModeRef.current,
                      )
                    }}
                  >
                    生成预览
                  </LoadingButton>
                  <LoadingButton
                    type="button"
                    size="sm"
                    loading={status === "saving" && previewPages.length > 0}
                    disabled={
                      previewPages.length === 0 ||
                      status === "loading" ||
                      status === "detecting"
                    }
                    onClick={() => {
                      if (!imageRef.current || !editorRef.current) return
                      void saveCorners(
                        editorRef.current.getCorners(),
                        imageRef.current,
                        pageModeRef.current,
                      )
                    }}
                  >
                    保存并应用到主画布
                  </LoadingButton>
                </div>
                {previewPages.length > 0 ? (
                  <div className="mt-2 text-xs text-muted-foreground">
                    主画布不会自动替换；点击“保存并应用到主画布”后，检测题目区域会基于下面这组校正页重新运行。
                  </div>
                ) : null}
              </div>
              <div className="max-h-[50vh] space-y-3 overflow-y-auto rounded-md border p-3">
                <div className="text-sm font-medium">预览页</div>
                {previewPages.length === 0 ? (
                  <div className="text-xs text-muted-foreground">
                    还没有生成预览。
                  </div>
                ) : (
                  previewPages.map((page) => (
                    <div
                      key={`${page.pageNumber}-${page.name}`}
                      className="space-y-1"
                    >
                      <div className="text-xs text-muted-foreground">
                        第 {page.pageNumber} 页 · {page.name}
                        {page.orientation?.rotation != null
                          ? ` · 旋转 ${page.orientation.rotation}°`
                          : ""}
                      </div>
                      <img
                        src={page.imageUrl}
                        alt={page.name}
                        className="block w-full rounded-md border bg-white"
                      />
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

async function uploadExamFiles(examId: string, files: File[]) {
  const formData = new FormData()
  for (const file of files) formData.append("files", file)
  formData.append("document_type", "blank_exam")
  formData.append("preprocess", "auto")
  const response = await fetch(
    `${OpenAPI.BASE || ""}/api/v1/exams/${examId}/files/batch`,
    {
      method: "POST",
      headers: authHeaders(),
      body: formData,
    },
  )
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}

async function reorderExamFiles(examId: string, documentIds: string[]) {
  const response = await fetch(
    `${OpenAPI.BASE || ""}/api/v1/exams/${examId}/files/order`,
    {
      method: "PATCH",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ document_ids: documentIds }),
    },
  )
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}

async function deleteExamFile(examId: string, documentId: string) {
  return workflowApi<ExamDocumentsPublic>(
    `/exams/${examId}/files/${documentId}`,
    {
      method: "DELETE",
    },
  )
}

async function clearExamPaperFiles(examId: string) {
  return workflowApi<ExamDocumentsPublic>(`/exams/${examId}/files`, {
    method: "DELETE",
  })
}

export function ExamFilesContent({
  exam,
  active = true,
}: {
  exam: ExamPublic
  active?: boolean
}) {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [inputKey, setInputKey] = useState(0)
  const [reviewDocument, setReviewDocument] =
    useState<ExamDocumentPublic | null>(null)
  const [clearConfirmOpen, setClearConfirmOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<ExamDocumentPublic | null>(
    null,
  )
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryKey = ["exam-files", exam.id]

  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () => ExamsService.readExamFiles({ examId: exam.id }),
    enabled: active,
  })

  const uploadMutation = useMutation({
    mutationFn: (files: File[]) => uploadExamFiles(exam.id, files),
    onSuccess: () => {
      showSuccessToast("试卷导入成功")
      setSelectedFiles([])
      setInputKey((value) => value + 1)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey })
    },
  })

  const reorderMutation = useMutation({
    mutationFn: (documentIds: string[]) =>
      reorderExamFiles(exam.id, documentIds),
    onSuccess: () => showSuccessToast("页面顺序已保存"),
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (documentId: string) => deleteExamFile(exam.id, documentId),
    onSuccess: (nextDocuments) => {
      showSuccessToast("已删除导入文件")
      setDeleteTarget(null)
      queryClient.setQueryData(queryKey, nextDocuments)
      queryClient.invalidateQueries({ queryKey })
      queryClient.invalidateQueries({ queryKey: ["exam-regions", exam.id] })
      queryClient.removeQueries({ queryKey: ["exam-file-page-image", exam.id] })
      queryClient.removeQueries({
        queryKey: ["exam-region-candidates", exam.id],
      })
    },
    onError: handleError.bind(showErrorToast),
  })

  const clearMutation = useMutation({
    mutationFn: () => clearExamPaperFiles(exam.id),
    onSuccess: (nextDocuments) => {
      showSuccessToast("已清空导入的卷子")
      setClearConfirmOpen(false)
      queryClient.setQueryData(queryKey, nextDocuments)
      queryClient.invalidateQueries({ queryKey })
      queryClient.invalidateQueries({ queryKey: ["exam-regions", exam.id] })
      queryClient.removeQueries({ queryKey: ["exam-file-page-image", exam.id] })
      queryClient.removeQueries({
        queryKey: ["exam-region-candidates", exam.id],
      })
    },
    onError: handleError.bind(showErrorToast),
  })

  const autoRectifyAllMutation = useMutation({
    mutationFn: () => autoRectifyExamDocuments({ examId: exam.id }),
    onSuccess: (nextDocuments) => {
      showSuccessToast("全卷重新扫描完成")
      queryClient.setQueryData(queryKey, nextDocuments)
      queryClient.invalidateQueries({ queryKey })
      queryClient.invalidateQueries({ queryKey: ["exam-regions", exam.id] })
      queryClient.removeQueries({ queryKey: ["exam-file-page-image", exam.id] })
      queryClient.removeQueries({
        queryKey: ["exam-region-candidates", exam.id],
      })
    },
    onError: handleError.bind(showErrorToast),
  })

  const documents = (data?.data ?? []).filter(
    (document) => document.document_type === "blank_exam",
  )
  let pageOffset = 0
  const documentsWithRange = documents.map((document) => {
    const pageCount = document.page_count ?? 1
    const firstPage = pageOffset + 1
    pageOffset += pageCount
    return { document, firstPage, lastPage: pageOffset }
  })

  const moveUploadedDocument = (index: number, offset: -1 | 1) => {
    const nextDocuments = moveItem(documents, index, offset)
    if (nextDocuments === documents) return
    reorderMutation.mutate(nextDocuments.map((document) => document.id))
  }

  return (
    <>
      <div className="grid gap-5">
        <div className="grid gap-3 rounded-md border p-4">
          <div>
            <div className="text-sm font-medium">添加卷子图片/PDF</div>
            <p className="mt-1 text-xs text-muted-foreground">
              可一次选择多个图片或 PDF；文件顺序就是整张卷子的页面顺序，PDF
              内部页序保持不变。
            </p>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <Input
              key={inputKey}
              data-testid="exam-file-input"
              type="file"
              accept=".pdf,image/png,image/jpeg"
              multiple
              onChange={(event) =>
                setSelectedFiles(Array.from(event.target.files ?? []))
              }
            />
            <LoadingButton
              data-testid="exam-file-upload-button"
              type="button"
              loading={uploadMutation.isPending}
              disabled={selectedFiles.length === 0}
              onClick={() => uploadMutation.mutate(selectedFiles)}
              className="sm:w-36"
            >
              <FileUp />
              上传 {selectedFiles.length || ""}
            </LoadingButton>
          </div>

          {selectedFiles.length > 0 && (
            <div className="rounded-md bg-muted/40 p-3">
              <div className="mb-2 text-xs font-medium text-muted-foreground">
                上传顺序
              </div>
              <div className="grid gap-2">
                {selectedFiles.map((file, index) => (
                  <div
                    key={`${file.name}-${file.size}-${file.lastModified}`}
                    className="flex items-center gap-2 text-sm"
                  >
                    <span className="w-8 text-muted-foreground">
                      {index + 1}.
                    </span>
                    <span className="min-w-0 flex-1 truncate">{file.name}</span>
                    <span className="text-xs text-muted-foreground">
                      {formatBytes(file.size)}
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      disabled={index === 0}
                      onClick={() =>
                        setSelectedFiles((files) => moveItem(files, index, -1))
                      }
                    >
                      <ArrowUp />
                      <span className="sr-only">上移</span>
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      disabled={index === selectedFiles.length - 1}
                      onClick={() =>
                        setSelectedFiles((files) => moveItem(files, index, 1))
                      }
                    >
                      <ArrowDown />
                      <span className="sr-only">下移</span>
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="rounded-md border">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <div>
              <span className="text-sm font-medium">整张卷子的页面顺序</span>
              <div className="text-xs text-muted-foreground">
                {documents.length} 个源文件，共 {pageOffset} 页
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="secondary">{pageOffset} 页</Badge>
              {documents.length > 0 && (
                <LoadingButton
                  type="button"
                  variant="outline"
                  size="sm"
                  loading={autoRectifyAllMutation.isPending}
                  disabled={
                    uploadMutation.isPending ||
                    reorderMutation.isPending ||
                    deleteMutation.isPending ||
                    clearMutation.isPending
                  }
                  onClick={() => autoRectifyAllMutation.mutate()}
                >
                  <ScanLine />
                  全卷重新扫描
                </LoadingButton>
              )}
              {documents.length > 0 && (
                <LoadingButton
                  type="button"
                  variant="outline"
                  size="sm"
                  loading={clearMutation.isPending}
                  disabled={
                    uploadMutation.isPending ||
                    reorderMutation.isPending ||
                    deleteMutation.isPending
                  }
                  onClick={() => setClearConfirmOpen(true)}
                >
                  <Trash2 />
                  清空已导入
                </LoadingButton>
              )}
            </div>
          </div>
          {isLoading ? (
            <div className="flex items-center gap-2 px-4 py-8 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              正在加载页面
            </div>
          ) : documents.length === 0 ? (
            <div className="px-4 py-8 text-sm text-muted-foreground">
              这场考试还没有导入卷子。请先上传空白卷，或上传一份代表学生卷用于识别题目内容。
            </div>
          ) : (
            <div className="divide-y">
              {documentsWithRange.map(
                ({ document, firstPage, lastPage }, index) => {
                  const warnings = readScanWarnings(document)
                  const strategy = formatScanStrategy(document)
                  const scanTotalMs = readScanTotalMs(document)
                  return (
                    <div key={document.id} className="grid gap-2 px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-sm font-medium text-primary">
                          {index + 1}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium">
                            {document.stored_file.original_filename}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {formatDocumentType(document.document_type)} · 第{" "}
                            {firstPage}
                            {lastPage > firstPage ? `–${lastPage}` : ""} 页 ·{" "}
                            {formatBytes(document.stored_file.size_bytes)}
                          </div>
                          <div className="mt-1 flex flex-wrap items-center gap-1.5">
                            <Badge
                              variant={
                                document.preprocessing_status === "review"
                                  ? "destructive"
                                  : "secondary"
                              }
                            >
                              {formatPreprocessingStatus(
                                document.preprocessing_status,
                              )}
                              {document.preprocessing_quality != null
                                ? ` · ${Math.round(document.preprocessing_quality * 100)}%`
                                : ""}
                            </Badge>
                            {strategy && (
                              <Badge variant="outline">{strategy}</Badge>
                            )}
                            {document.original_stored_file_id && (
                              <Badge variant="outline">已保留原图</Badge>
                            )}
                            {scanTotalMs != null && (
                              <Badge variant="outline">
                                扫描 {(scanTotalMs / 1000).toFixed(1)} 秒
                              </Badge>
                            )}
                          </div>
                        </div>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={!canReviewDocumentCorners(document)}
                          onClick={() => setReviewDocument(document)}
                        >
                          <ScanLine />
                          复核四角
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="icon-sm"
                          disabled={index === 0 || reorderMutation.isPending}
                          onClick={() => moveUploadedDocument(index, -1)}
                        >
                          <ArrowUp />
                          <span className="sr-only">向前移动</span>
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="icon-sm"
                          disabled={
                            index === documents.length - 1 ||
                            reorderMutation.isPending
                          }
                          onClick={() => moveUploadedDocument(index, 1)}
                        >
                          <ArrowDown />
                          <span className="sr-only">向后移动</span>
                        </Button>
                        <LoadingButton
                          type="button"
                          variant="outline"
                          size="sm"
                          loading={
                            deleteMutation.isPending &&
                            deleteMutation.variables === document.id
                          }
                          disabled={
                            clearMutation.isPending ||
                            reorderMutation.isPending ||
                            uploadMutation.isPending
                          }
                          onClick={() => setDeleteTarget(document)}
                        >
                          <Trash2 />
                          删除
                        </LoadingButton>
                      </div>
                      {warnings.length > 0 && (
                        <div className="ml-11 rounded-md bg-destructive/5 px-3 py-2 text-xs text-destructive">
                          {warnings
                            .slice(0, 2)
                            .map(formatScanWarning)
                            .join("；")}
                          {warnings.length > 2
                            ? `；另有 ${warnings.length - 2} 项提示`
                            : ""}
                        </div>
                      )}
                      <PreprocessingPreview
                        examId={exam.id}
                        document={document}
                      />
                      <SplitPagePreview
                        examId={exam.id}
                        documentId={document.id}
                        pageCount={document.page_count ?? 1}
                      />
                    </div>
                  )
                },
              )}
            </div>
          )}
        </div>
      </div>
      <DocumentCornerReviewDialog
        examId={exam.id}
        document={reviewDocument}
        open={Boolean(reviewDocument)}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) setReviewDocument(null)
        }}
        onSaved={(updatedDocument) => {
          showSuccessToast("四角校正已保存")
          queryClient.setQueryData<{
            data: ExamDocumentPublic[]
            count: number
          }>(queryKey, (current) => {
            if (!current) return current
            return {
              ...current,
              data: current.data.map((document) =>
                document.id === updatedDocument.id ? updatedDocument : document,
              ),
            }
          })
          queryClient.removeQueries({
            queryKey: ["exam-file-page-image", exam.id],
          })
          queryClient.invalidateQueries({ queryKey })
        }}
      />
      <ConfirmDialog
        open={clearConfirmOpen}
        onOpenChange={setClearConfirmOpen}
        title="清空已导入的卷子"
        description="确定清空当前已导入的卷子文件吗？题目区域、识别记录、已确认题目、标准答案和批改任务也会一起清空。"
        confirmText="清空"
        loading={clearMutation.isPending}
        onConfirm={() => clearMutation.mutate()}
      />
      <ConfirmDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) setDeleteTarget(null)
        }}
        title="删除导入文件"
        description={
          deleteTarget
            ? `确定删除“${deleteTarget.stored_file.original_filename}”吗？关联题目区域也会一起删除。`
            : undefined
        }
        confirmText="删除"
        loading={deleteMutation.isPending}
        onConfirm={() => {
          if (deleteTarget) deleteMutation.mutate(deleteTarget.id)
        }}
      />
    </>
  )
}

export default function ExamFilesDialog({
  exam,
  trigger,
}: {
  exam: ExamPublic
  trigger?: ReactNode
}) {
  const [isOpen, setIsOpen] = useState(false)

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button variant="outline" size="sm">
            <FileText />
            导入试卷
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{exam.title}</DialogTitle>
          <DialogDescription>
            导入这套卷子的图片或
            PDF。一份卷子可以由多张图片组成；按页面顺序上传即可。优先用空白卷，没有空白卷时也可以用一份学生卷，后续识别会把手写作答和印刷题干分开。
          </DialogDescription>
        </DialogHeader>
        <ExamFilesContent exam={exam} active={isOpen} />
      </DialogContent>
    </Dialog>
  )
}
