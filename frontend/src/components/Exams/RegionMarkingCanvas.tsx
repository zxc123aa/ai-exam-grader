import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import {
  AlertTriangle,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleCheck,
  Save,
  ScanLine,
  Sparkles,
  Trash2,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"

import {
  ApiError,
  type ExamDocumentPublic,
  type ExamPublic,
  type ExamRegionCandidate,
  type ExamRegionPublic,
  ExamsService,
  OpenAPI,
} from "@/client"
import { Tag } from "@/components/Common/Tag"
import ExamFilesDialog, {
  DocumentCornerReviewDialog,
} from "@/components/Exams/ExamFilesDialog"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import useCustomToast from "@/hooks/useCustomToast"
import { autoRectifyExamDocuments } from "@/lib/document-normalizer"
import { workflowApi } from "@/lib/workflow-api"
import { handleError } from "@/utils"

type DraftRegion = {
  x: number
  y: number
  width: number
  height: number
}

type CandidateDraft = DraftRegion & {
  label: string
  confidence: number
  source: string
  reasons: string[]
}

type ReferenceRecognitionItem = {
  id?: string
  blockId?: string
  sourceBlockIds?: string[]
  sourceLabel?: string
  questionNumber?: string
  question?: string
  studentAnswer?: string
  answerType?: string
  confidence?: number
  notes?: string
  elapsedMs?: number
}

type ReferenceRecognitionResponse = {
  results: ReferenceRecognitionItem[]
  blocks?: ReferenceRecognitionBlock[]
  layouts?: Array<{ pageId?: string; rotation?: number }>
  requestedPageId?: string
  contextPageIds?: string[]
  updatedPageIds?: string[]
  timing?: {
    orientationMs?: number
    layoutMs?: number
    layoutModelMs?: number
    refinementMs?: number
    cropMs?: number
    ocrMs?: number
    totalElapsedMs?: number
  }
  concurrency?: number
  modelRequestCount?: number
  fallbackBatchCount?: number
}

type ReferenceRecognitionBlock = {
  id?: string
  pageId?: string
  label?: string
  questionNumber?: string
  xmin?: number
  ymin?: number
  xmax?: number
  ymax?: number
}

type RecognitionRun = { id: string }

type AggregatedRecognitionItem = {
  key: string
  questionNumber: string
  question: string
  studentAnswer: string
  answerType?: string
  confidence: number | null
  elapsedMs: number
  sourcePages: string[]
  sourceCount: number
}

type SegmentationEngine =
  | "gemini_layout_v1"
  | "layout_projection_v0"
  | "layout_ocr_anchor_v1"

type DragMode = "draw" | "move" | "resize"

type Interaction = {
  mode: DragMode
  regionId?: string
  startPoint: { x: number; y: number }
  startRegion?: DraftRegion
}

function clamp(value: number) {
  return Math.max(0, Math.min(1, value))
}

function normalizeRegion(
  startX: number,
  startY: number,
  endX: number,
  endY: number,
) {
  const x = clamp(Math.min(startX, endX))
  const y = clamp(Math.min(startY, endY))
  const right = clamp(Math.max(startX, endX))
  const bottom = clamp(Math.max(startY, endY))
  return {
    x,
    y,
    width: Math.max(0, right - x),
    height: Math.max(0, bottom - y),
  }
}

function moveRegion(region: DraftRegion, dx: number, dy: number) {
  return {
    ...region,
    x: clamp(Math.min(region.x + dx, 1 - region.width)),
    y: clamp(Math.min(region.y + dy, 1 - region.height)),
  }
}

function resizeRegion(region: DraftRegion, point: { x: number; y: number }) {
  const right = clamp(Math.max(point.x, region.x + 0.01))
  const bottom = clamp(Math.max(point.y, region.y + 0.01))
  return {
    ...region,
    width: Math.max(0.01, right - region.x),
    height: Math.max(0.01, bottom - region.y),
  }
}

function normalizeTextChunk(value: unknown) {
  return String(value || "").trim()
}

function naturalQuestionKey(value: string) {
  return value
    .split(/(\d+)/)
    .filter(Boolean)
    .map((part) => (/^\d+$/.test(part) ? part.padStart(8, "0") : part))
    .join("")
}

function makePageKey(documentId: string, pageNumber: number) {
  return `${documentId}:page:${pageNumber}`
}

/** 识别结果缓存在浏览器本地：翻页、刷新、误关都不丢，确认入库后清除。 */
type RecognitionCachePayload = {
  response: ReferenceRecognitionResponse | null
  clearedPageKeys: string[]
  recognizedPageKeys: string[]
}

function recognitionCacheKey(examId: string) {
  return `marking-recognition:${examId}`
}

function loadRecognitionCache(examId: string): RecognitionCachePayload | null {
  try {
    const raw = localStorage.getItem(recognitionCacheKey(examId))
    if (!raw) return null
    return JSON.parse(raw) as RecognitionCachePayload
  } catch {
    return null
  }
}

function formatPageLabel(pageId: string, documents: ExamDocumentPublic[]) {
  const [documentId, rawPage] = pageId.split(":page:")
  const documentIndex = documents.findIndex((item) => item.id === documentId)
  const document = documents[documentIndex]
  const pageNumber = Number(rawPage || 1) || 1
  const fileLabel =
    documentIndex >= 0 ? `文件${documentIndex + 1}` : documentId.slice(0, 8)
  const pageLabel =
    (document?.page_count ?? 1) > 1
      ? `PDF第${pageNumber}页`
      : `第${pageNumber}页`
  return `${fileLabel}/${pageLabel}`
}

function recognitionItemPageIds(
  item: ReferenceRecognitionItem,
  blockPageById: Map<string, string>,
) {
  const sourceIds =
    Array.isArray(item.sourceBlockIds) && item.sourceBlockIds.length > 0
      ? item.sourceBlockIds
      : [item.blockId, item.id].filter(Boolean)
  return Array.from(
    new Set(
      sourceIds
        .map((sourceId) => blockPageById.get(String(sourceId)))
        .filter((pageId): pageId is string => Boolean(pageId)),
    ),
  )
}

function blockPageMap(blocks: ReferenceRecognitionBlock[] = []) {
  const map = new Map<string, string>()
  for (const block of blocks) {
    if (block.id && block.pageId) {
      map.set(String(block.id), String(block.pageId))
    }
  }
  return map
}

function mergeCurrentPageRecognitionResponse(
  previous: ReferenceRecognitionResponse | null,
  next: ReferenceRecognitionResponse,
  currentPageKey: string,
): ReferenceRecognitionResponse {
  if (!previous) return next
  const previousBlockPageById = blockPageMap(previous.blocks)
  const updatedPageKeys = new Set(
    next.updatedPageIds?.length
      ? next.updatedPageIds
      : [
          currentPageKey,
          ...(next.blocks ?? [])
            .map((block) => block.pageId)
            .filter((pageId): pageId is string => Boolean(pageId)),
        ],
  )
  const touchesUpdatedPage = (item: ReferenceRecognitionItem) => {
    const pageIds = recognitionItemPageIds(item, previousBlockPageById)
    return pageIds.some((pageId) => updatedPageKeys.has(pageId))
  }
  const nextSourceBlockIds = new Set(
    next.results.flatMap((item) =>
      Array.isArray(item.sourceBlockIds) && item.sourceBlockIds.length > 0
        ? item.sourceBlockIds.map(String)
        : [item.blockId, item.id].filter(Boolean).map(String),
    ),
  )
  const sharesNextSourceBlock = (item: ReferenceRecognitionItem) => {
    const sourceIds =
      Array.isArray(item.sourceBlockIds) && item.sourceBlockIds.length > 0
        ? item.sourceBlockIds
        : [item.blockId, item.id].filter(Boolean)
    return sourceIds.some((sourceId) =>
      nextSourceBlockIds.has(String(sourceId)),
    )
  }
  const previousBlocks = (previous.blocks ?? []).filter(
    (block) =>
      (!block.pageId || !updatedPageKeys.has(block.pageId)) &&
      (!block.id || !nextSourceBlockIds.has(String(block.id))),
  )
  return {
    ...next,
    results: [
      ...previous.results.filter(
        (item) => !touchesUpdatedPage(item) && !sharesNextSourceBlock(item),
      ),
      ...next.results,
    ],
    blocks: [...previousBlocks, ...(next.blocks ?? [])],
    timing: {
      ...previous.timing,
      ...next.timing,
    },
    concurrency: next.concurrency ?? previous.concurrency,
    modelRequestCount:
      (previous.modelRequestCount ?? 0) + (next.modelRequestCount ?? 0),
    fallbackBatchCount:
      (previous.fallbackBatchCount ?? 0) + (next.fallbackBatchCount ?? 0),
  }
}

function aggregateRecognitionResults(
  results: ReferenceRecognitionItem[],
  blockPageById: Map<string, string>,
  documents: ExamDocumentPublic[],
) {
  return results
    .map<AggregatedRecognitionItem>((item, index) => {
      const confidence = Number(item.confidence)
      const sourceBlockIds =
        item.sourceBlockIds?.length && item.sourceBlockIds.length > 0
          ? item.sourceBlockIds
          : [item.blockId, item.id].filter(Boolean)
      return {
        key: String(item.id || item.blockId || `result-${index + 1}`),
        questionNumber:
          normalizeTextChunk(item.questionNumber) || `未编号-${index + 1}`,
        question: normalizeTextChunk(item.question),
        studentAnswer: normalizeTextChunk(item.studentAnswer),
        answerType: item.answerType,
        confidence: Number.isFinite(confidence) ? confidence : null,
        elapsedMs: Number(item.elapsedMs || 0),
        sourcePages: recognitionItemPageIds(item, blockPageById).map((pageId) =>
          formatPageLabel(pageId, documents),
        ),
        sourceCount: sourceBlockIds.length,
      }
    })
    .sort((left, right) =>
      naturalQuestionKey(left.questionNumber).localeCompare(
        naturalQuestionKey(right.questionNumber),
        "zh-Hans-CN",
        { numeric: true },
      ),
    )
}

function getPoint(event: React.PointerEvent<HTMLElement>, target: HTMLElement) {
  const rect = target.getBoundingClientRect()
  return {
    x: clamp((event.clientX - rect.left) / rect.width),
    y: clamp((event.clientY - rect.top) / rect.height),
  }
}

function hasPerspectivePreprocessing(document: ExamDocumentPublic) {
  const metadata = document.preprocessing_metadata
  const source = metadata?.source
  const pages = metadata?.pages
  return Boolean(
    document.original_stored_file_id &&
      document.stored_file.content_type === "application/pdf" &&
      (source === "mobile_document_preprocessing_v2" ||
        source === "manual_quad_document_preprocessing_v1") &&
      Array.isArray(pages) &&
      pages.length > 0,
  )
}

function formatPerspectiveStatus(document: ExamDocumentPublic) {
  if (hasPerspectivePreprocessing(document)) {
    const quality =
      document.preprocessing_quality != null
        ? ` · 质量 ${Math.round(document.preprocessing_quality * 100)}%`
        : ""
    return `已使用透视校正扫描页${quality}`
  }
  return "当前是原始照片：版面分析只做转正/分题，不等于四角透视摆正。请先在“导入试卷 → 复核四角”生成扫描页。"
}

async function fetchPageImageBlob(
  examId: string,
  documentId: string,
  pageNumber: number,
  cacheKey?: string,
) {
  const token = localStorage.getItem("access_token")
  const base = OpenAPI.BASE || ""
  const response = await fetch(
    `${base}/api/v1/exams/${examId}/files/${documentId}/pages/${pageNumber}/image${
      cacheKey ? `?stored_file_id=${encodeURIComponent(cacheKey)}` : ""
    }`,
    {
      cache: "no-store",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        "Cache-Control": "no-cache",
      },
    },
  )
  if (!response.ok) {
    throw new ApiError(
      {
        method: "GET",
        url: "/api/v1/exams/{exam_id}/files/{document_id}/pages/{page_number}/image",
      },
      {
        url: response.url,
        ok: response.ok,
        status: response.status,
        statusText: response.statusText,
        body: await response.text(),
      },
      "Failed to load exam file",
    )
  }
  return response.blob()
}

async function fetchSourceImageBlob(examId: string, documentId: string) {
  const token = localStorage.getItem("access_token")
  const base = OpenAPI.BASE || ""
  const response = await fetch(
    `${base}/api/v1/exams/${examId}/files/${documentId}/source-image`,
    {
      cache: "no-store",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        "Cache-Control": "no-cache",
      },
    },
  )
  if (!response.ok) {
    throw new ApiError(
      {
        method: "GET",
        url: "/api/v1/exams/{exam_id}/files/{document_id}/source-image",
      },
      {
        url: response.url,
        ok: response.ok,
        status: response.status,
        statusText: response.statusText,
        body: await response.text(),
      },
      "Failed to load exam file source image",
    )
  }
  return response.blob()
}

async function recognizeReferenceDocuments(
  examId: string,
  documents: ExamDocumentPublic[],
): Promise<ReferenceRecognitionResponse> {
  const token = localStorage.getItem("access_token")
  const response = await fetch(
    `${OpenAPI.BASE || ""}/api/v1/exams/${examId}/files/reference-recognition`,
    {
      method: "POST",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        document_ids: documents.map((document) => document.id),
      }),
    },
  )
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}

async function recognizeReferenceDocumentPage(
  examId: string,
  documentId: string,
  pageNumber: number,
): Promise<ReferenceRecognitionResponse> {
  const token = localStorage.getItem("access_token")
  const response = await fetch(
    `${OpenAPI.BASE || ""}/api/v1/exams/${examId}/files/${documentId}/pages/${pageNumber}/reference-recognition`,
    {
      method: "POST",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    },
  )
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}

export default function RegionMarkingCanvas({
  examId,
  exam,
  documents,
  regions,
}: {
  examId: string
  exam?: ExamPublic
  documents: ExamDocumentPublic[]
  regions: ExamRegionPublic[]
}) {
  const [label, setLabel] = useState(`Q${regions.length + 1}`)
  const [draft, setDraft] = useState<DraftRegion | null>(null)
  const [interaction, setInteraction] = useState<Interaction | null>(null)
  const [selectedRegionId, setSelectedRegionId] = useState<string | null>(null)
  const [editingRegion, setEditingRegion] = useState<DraftRegion | null>(null)
  const [editingLabel, setEditingLabel] = useState("")
  const [cornerReviewOpen, setCornerReviewOpen] = useState(false)
  const [compareOpen, setCompareOpen] = useState(false)
  const [regionsPanelOpen, setRegionsPanelOpen] = useState(false)
  const [segmentationEngine, setSegmentationEngine] =
    useState<SegmentationEngine>("gemini_layout_v1")
  const canvasRef = useRef<HTMLDivElement | null>(null)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [appliedDocumentById, setAppliedDocumentById] = useState<
    Record<string, ExamDocumentPublic>
  >({})
  const [recognitionResponse, setRecognitionResponse] =
    useState<ReferenceRecognitionResponse | null>(
      () => loadRecognitionCache(examId)?.response ?? null,
    )
  const [clearedRecognitionPageKeys, setClearedRecognitionPageKeys] = useState<
    Set<string>
  >(() => new Set(loadRecognitionCache(examId)?.clearedPageKeys ?? []))
  const [recognizedTargetPageKeys, setRecognizedTargetPageKeys] = useState<
    Set<string>
  >(() => new Set(loadRecognitionCache(examId)?.recognizedPageKeys ?? []))
  useEffect(() => {
    try {
      localStorage.setItem(
        recognitionCacheKey(examId),
        JSON.stringify({
          response: recognitionResponse,
          clearedPageKeys: Array.from(clearedRecognitionPageKeys),
          recognizedPageKeys: Array.from(recognizedTargetPageKeys),
        } satisfies RecognitionCachePayload),
      )
    } catch {
      // 存储满了等异常不影响页面使用
    }
  }, [
    examId,
    recognitionResponse,
    clearedRecognitionPageKeys,
    recognizedTargetPageKeys,
  ])
  const [imageVersion, setImageVersion] = useState(0)
  const queryKey = ["exam-regions", examId]
  const effectiveDocuments = documents.map(
    (item) => appliedDocumentById[item.id] ?? item,
  )
  const documentCount = effectiveDocuments.length
  const paperPages = effectiveDocuments.flatMap((document) =>
    Array.from({ length: document.page_count ?? 1 }, (_, index) => ({
      document,
      sourcePageNumber: index + 1,
    })),
  )
  const pageCount = paperPages.length
  const [paperPageNumber, setPaperPageNumber] = useState(1)
  const currentPage = paperPages[paperPageNumber - 1] ?? paperPages[0]
  const document = (currentPage?.document ?? effectiveDocuments[0])!
  const documentIndex = Math.max(
    0,
    effectiveDocuments.findIndex((item) => item.id === document.id),
  )
  const pageNumber = currentPage?.sourcePageNumber ?? 1
  const currentRecognitionPageKey = makePageKey(document.id, pageNumber)
  const currentPageRecognitionMutation = useMutation({
    mutationFn: () =>
      recognizeReferenceDocumentPage(examId, document.id, pageNumber),
    onSuccess: (data) => {
      setRecognitionResponse((previous) =>
        mergeCurrentPageRecognitionResponse(
          previous,
          data,
          currentRecognitionPageKey,
        ),
      )
      setClearedRecognitionPageKeys((current) => {
        const next = new Set(current)
        next.delete(currentRecognitionPageKey)
        return next
      })
      setRecognizedTargetPageKeys((current) => {
        const next = new Set(current)
        next.add(currentRecognitionPageKey)
        return next
      })
    },
    onError: (error: Error) => showErrorToast(error.message),
  })
  const recognitionMutation = useMutation({
    mutationFn: () => recognizeReferenceDocuments(examId, effectiveDocuments),
    onSuccess: (data) => {
      setRecognitionResponse(data)
      setClearedRecognitionPageKeys(new Set())
      setRecognizedTargetPageKeys(
        new Set(
          paperPages.map((page) =>
            makePageKey(page.document.id, page.sourcePageNumber),
          ),
        ),
      )
    },
    onError: (error: Error) => showErrorToast(error.message),
  })
  const autoRectifyAllMutation = useMutation({
    mutationFn: () => autoRectifyExamDocuments({ examId }),
    onSuccess: (nextDocuments) => {
      const updatedDocuments = nextDocuments.data ?? []
      queryClient.setQueryData(["exam-files", examId], nextDocuments)
      queryClient.invalidateQueries({ queryKey: ["exam-files", examId] })
      queryClient.removeQueries({ queryKey: ["exam-file-page-image", examId] })
      queryClient.removeQueries({
        queryKey: ["exam-region-candidates", examId],
      })
      queryClient.invalidateQueries({ queryKey: ["exam-regions", examId] })
      setAppliedDocumentById(
        Object.fromEntries(
          updatedDocuments.map((updatedDocument) => [
            updatedDocument.id,
            updatedDocument,
          ]),
        ),
      )
      setImageVersion((value) => value + 1)
      setPaperPageNumber(1)
      setDraft(null)
      setSelectedRegionId(null)
      setContentUrl(null)
      setRecognitionResponse(null)
      setClearedRecognitionPageKeys(new Set())
      setRecognizedTargetPageKeys(new Set())
      setCompareOpen(false)
      showSuccessToast("全卷已重新摆正，请重新检测题目区域")
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const blobQuery = useQuery({
    queryKey: [
      "exam-file-page-image",
      examId,
      document.id,
      document.stored_file.id,
      pageNumber,
      imageVersion,
    ],
    queryFn: () =>
      fetchPageImageBlob(
        examId,
        document.id,
        pageNumber,
        `${document.stored_file.id}-${imageVersion}`,
      ),
  })
  const sourceImageQuery = useQuery({
    queryKey: [
      "exam-file-source-image",
      examId,
      document.id,
      document.original_stored_file_id,
    ],
    queryFn: () => fetchSourceImageBlob(examId, document.id),
    enabled: compareOpen && hasPerspectivePreprocessing(document),
  })
  const candidatesQuery = useQuery({
    queryKey: [
      "exam-region-candidates",
      examId,
      document.id,
      document.stored_file.id,
      pageNumber,
      segmentationEngine,
    ],
    queryFn: () =>
      ExamsService.readExamRegionCandidates({
        examId,
        documentId: document.id,
        pageNumber,
        engine: segmentationEngine,
      }),
    enabled: false,
  })
  const [contentUrl, setContentUrl] = useState<string | null>(null)
  const [sourceUrl, setSourceUrl] = useState<string | null>(null)
  const displayUrl = candidatesQuery.data?.upright_image || contentUrl
  const recognitionOrDetectionPending =
    candidatesQuery.isFetching ||
    currentPageRecognitionMutation.isPending ||
    recognitionMutation.isPending

  useEffect(() => {
    if (!blobQuery.data) {
      setContentUrl(null)
      return
    }
    const url = URL.createObjectURL(blobQuery.data)
    setContentUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [blobQuery.data])

  useEffect(() => {
    if (!sourceImageQuery.data) {
      setSourceUrl(null)
      return
    }
    const url = URL.createObjectURL(sourceImageQuery.data)
    setSourceUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [sourceImageQuery.data])

  const createMutation = useMutation({
    mutationFn: (region: DraftRegion) =>
      ExamsService.createExamRegion({
        examId,
        requestBody: {
          label: label.trim() || `Q${regions.length + 1}`,
          region_type: "question",
          page_number: pageNumber,
          exam_document_id: document.id,
          ...region,
        },
      }),
    onSuccess: () => {
      showSuccessToast("区域已保存")
      setDraft(null)
      setLabel(`Q${regions.length + 2}`)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey })
    },
  })

  const saveCandidatesMutation = useMutation({
    mutationFn: async ({
      candidates,
      documentId,
      sourcePageNumber,
    }: {
      candidates: CandidateDraft[]
      documentId: string
      sourcePageNumber: number
    }) => {
      for (const candidate of candidates) {
        await ExamsService.createExamRegion({
          examId,
          requestBody: {
            label: candidate.label,
            region_type: "question",
            page_number: sourcePageNumber,
            exam_document_id: documentId,
            x: candidate.x,
            y: candidate.y,
            width: candidate.width,
            height: candidate.height,
          },
        })
      }
    },
    onSuccess: () => {
      showSuccessToast("已保存本页全部 AI 候选区域")
      setDraft(null)
      setSelectedRegionId(null)
      queryClient.invalidateQueries({ queryKey })
    },
    onError: handleError.bind(showErrorToast),
  })

  const updateMutation = useMutation({
    mutationFn: ({
      regionId,
      region,
      nextLabel,
    }: {
      regionId: string
      region: DraftRegion
      nextLabel: string
    }) =>
      ExamsService.updateExamRegion({
        examId,
        regionId,
        requestBody: {
          label: nextLabel.trim() || "Untitled",
          exam_document_id: document.id,
          ...region,
        },
      }),
    onSuccess: () => {
      showSuccessToast("区域已更新")
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (regionId: string) =>
      ExamsService.deleteExamRegion({ examId, regionId }),
    onSuccess: () => {
      showSuccessToast("区域已删除")
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey })
    },
  })

  const pageRegions = regions.filter(
    (region) =>
      (region.page_number ?? 1) === pageNumber &&
      (region.exam_document_id === document.id ||
        (!region.exam_document_id && documentCount === 1)),
  )
  const candidateDrafts: CandidateDraft[] = (
    candidatesQuery.data?.data ?? []
  ).map((candidate: ExamRegionCandidate) => ({
    label: candidate.label,
    confidence: candidate.confidence,
    source: candidate.source,
    reasons: candidate.reasons ?? [],
    x: candidate.x,
    y: candidate.y,
    width: candidate.width,
    height: candidate.height,
  }))
  const selectedRegion = pageRegions.find(
    (region) => region.id === selectedRegionId,
  )
  // 区域面板默认折叠；拖动新框、检测到候选、选中已有区域时自动展开。
  const regionsExpanded =
    regionsPanelOpen ||
    Boolean(draft) ||
    candidateDrafts.length > 0 ||
    Boolean(selectedRegionId)
  const blockPageById = useMemo(() => {
    return blockPageMap(recognitionResponse?.blocks)
  }, [recognitionResponse?.blocks])
  const visibleRecognitionResults = useMemo(() => {
    if (!recognitionResponse) return []
    return recognitionResponse.results.filter((item) => {
      const pageIds = recognitionItemPageIds(item, blockPageById)
      if (pageIds.length === 0) return true
      return !pageIds.every((pageId) => clearedRecognitionPageKeys.has(pageId))
    })
  }, [blockPageById, clearedRecognitionPageKeys, recognitionResponse])
  const currentPageRecognitionCount = useMemo(
    () =>
      visibleRecognitionResults.filter((item) =>
        recognitionItemPageIds(item, blockPageById).includes(
          currentRecognitionPageKey,
        ),
      ).length,
    [blockPageById, currentRecognitionPageKey, visibleRecognitionResults],
  )
  const currentPageAggregatedRecognitionResults = useMemo(
    () =>
      aggregateRecognitionResults(
        visibleRecognitionResults.filter((item) =>
          recognitionItemPageIds(item, blockPageById).includes(
            currentRecognitionPageKey,
          ),
        ),
        blockPageById,
        effectiveDocuments,
      ),
    [
      blockPageById,
      currentRecognitionPageKey,
      effectiveDocuments,
      visibleRecognitionResults,
    ],
  )
  const aggregatedRecognitionResults = useMemo(
    () =>
      aggregateRecognitionResults(
        visibleRecognitionResults,
        blockPageById,
        effectiveDocuments,
      ),
    [blockPageById, effectiveDocuments, visibleRecognitionResults],
  )
  const allPaperPageKeys = useMemo(
    () =>
      paperPages.map((page) =>
        makePageKey(page.document.id, page.sourcePageNumber),
      ),
    [paperPages],
  )
  const recognizedPageCount = allPaperPageKeys.filter((pageKey) =>
    recognizedTargetPageKeys.has(pageKey),
  ).length
  const recognitionReadyForConfirmation =
    Boolean(recognitionResponse) &&
    visibleRecognitionResults.length > 0 &&
    recognizedPageCount === allPaperPageKeys.length
  const importRecognitionMutation = useMutation({
    mutationFn: () => {
      if (!recognitionResponse) throw new Error("当前没有可保存的识别结果")
      return workflowApi<RecognitionRun>(
        `/exams/${examId}/question-recognition-runs/from-marking`,
        {
          method: "POST",
          body: JSON.stringify({
            document_ids: effectiveDocuments.map((item) => item.id),
            covered_page_ids: allPaperPageKeys,
            results: visibleRecognitionResults.map((item) => ({
              id: item.id,
              blockId: item.blockId,
              sourceBlockIds: item.sourceBlockIds,
              sourceLabel: item.sourceLabel,
              questionNumber: item.questionNumber,
              question: item.question,
              studentAnswer: item.studentAnswer,
              answerType: item.answerType,
              confidence: item.confidence,
              notes: item.notes,
              elapsedMs: item.elapsedMs,
            })),
            blocks: (recognitionResponse.blocks ?? []).map((block) => ({
              id: block.id,
              pageId: block.pageId,
              label: block.label,
              questionNumber: block.questionNumber,
              xmin: block.xmin,
              ymin: block.ymin,
              xmax: block.xmax,
              ymax: block.ymax,
            })),
            layouts: (recognitionResponse.layouts ?? []).map((layout) => ({
              pageId: layout.pageId,
              rotation: layout.rotation,
            })),
            timing: recognitionResponse.timing ?? {},
          }),
        },
      )
    },
    onSuccess: (run) => {
      // 已入库，本地缓存功成身退
      localStorage.removeItem(recognitionCacheKey(examId))
      showSuccessToast("识别结果已保存，请确认题目后制作标准答案")
      navigate({
        to: "/exams/$examId/questions",
        params: { examId },
        search: { runId: run.id },
      })
    },
    onError: (error: Error) => showErrorToast(error.message),
  })
  useEffect(() => {
    setPaperPageNumber((value) => Math.min(Math.max(value, 1), pageCount))
  }, [pageCount])

  useEffect(() => {
    if (!document.id || pageNumber < 1) return
    setSelectedRegionId(null)
    setDraft(null)
    setInteraction(null)
  }, [document.id, pageNumber])

  useEffect(() => {
    if (!candidatesQuery.isError) return
    showErrorToast(candidatesQuery.error.message || "区域检测失败")
  }, [candidatesQuery.error, candidatesQuery.isError, showErrorToast])

  useEffect(() => {
    if (!selectedRegion) {
      setEditingRegion(null)
      setEditingLabel("")
      return
    }
    // selectedRegion 每渲染都是新对象（上游 filter 未 memo），
    // 值没变时保持原引用，避免 setState 触发无限渲染循环
    setEditingRegion((current) =>
      current &&
      current.x === selectedRegion.x &&
      current.y === selectedRegion.y &&
      current.width === selectedRegion.width &&
      current.height === selectedRegion.height
        ? current
        : {
            x: selectedRegion.x,
            y: selectedRegion.y,
            width: selectedRegion.width,
            height: selectedRegion.height,
          },
    )
    setEditingLabel(selectedRegion.label)
  }, [selectedRegion])

  const saveSelectedRegion = () => {
    if (!selectedRegionId || !editingRegion) return
    updateMutation.mutate({
      regionId: selectedRegionId,
      region: editingRegion,
      nextLabel: editingLabel,
    })
  }

  const handlePerspectiveSaved = (updatedDocument: ExamDocumentPublic) => {
    const updatedDocumentIndex = documents.findIndex(
      (item) => item.id === updatedDocument.id,
    )
    const firstPageOfUpdatedDocument =
      updatedDocumentIndex >= 0
        ? documents
            .slice(0, updatedDocumentIndex)
            .reduce((sum, item) => sum + (item.page_count ?? 1), 0) + 1
        : 1

    queryClient.setQueryData<{ data: ExamDocumentPublic[]; count: number }>(
      ["exam-files", examId],
      (current) => {
        if (!current) return current
        return {
          ...current,
          data: current.data.map((document) =>
            document.id === updatedDocument.id ? updatedDocument : document,
          ),
        }
      },
    )
    queryClient.invalidateQueries({ queryKey: ["exam-files", examId] })
    queryClient.removeQueries({ queryKey: ["exam-file-page-image", examId] })
    queryClient.removeQueries({ queryKey: ["exam-region-candidates", examId] })
    setAppliedDocumentById((current) => ({
      ...current,
      [updatedDocument.id]: updatedDocument,
    }))
    setImageVersion((value) => value + 1)
    setPaperPageNumber(firstPageOfUpdatedDocument)
    setDraft(null)
    setSelectedRegionId(null)
    setContentUrl(null)
    setRecognitionResponse(null)
    setClearedRecognitionPageKeys(new Set())
    setRecognizedTargetPageKeys(new Set())
    showSuccessToast("已应用校正后的扫描页，请在新图上重新检测题目区域")
  }

  const selectCandidateDraft = (candidate: CandidateDraft) => {
    setSelectedRegionId(null)
    setDraft({
      x: candidate.x,
      y: candidate.y,
      width: candidate.width,
      height: candidate.height,
    })
    setLabel(candidate.label)
  }

  const detectCurrentPageRegions = async () => {
    // A previous candidate may be copied into the blue manual-edit draft.
    // It must not survive a new detection run and overlap fresh candidates.
    setDraft(null)
    setInteraction(null)
    setSelectedRegionId(null)
    setLabel(`Q${regions.length + 1}`)
    await candidatesQuery.refetch()
  }

  const clearCurrentPageRecognition = () => {
    if (!recognitionResponse || currentPageRecognitionCount === 0) return
    setClearedRecognitionPageKeys((current) => {
      const next = new Set(current)
      next.add(currentRecognitionPageKey)
      return next
    })
    setRecognizedTargetPageKeys((current) => {
      const next = new Set(current)
      next.delete(currentRecognitionPageKey)
      return next
    })
    showSuccessToast("已清除当前照片的识别结果")
  }

  const clearAllRecognition = () => {
    if (!recognitionResponse) return
    setRecognitionResponse(null)
    setClearedRecognitionPageKeys(new Set())
    setRecognizedTargetPageKeys(new Set())
    showSuccessToast("已清除本次全部识别结果")
  }

  if (blobQuery.isError) {
    return (
      <div className="rounded-md border p-8 text-sm text-destructive">
        无法加载图片预览。
      </div>
    )
  }

  if (blobQuery.isLoading || !displayUrl) {
    return (
      <div className="rounded-md border p-8 text-sm text-muted-foreground">
        正在加载图片预览
      </div>
    )
  }

  return (
    <div className="grid gap-4 xl:grid-cols-12">
      <div className="xl:col-span-full flex flex-col gap-3 rounded-2xl border bg-card px-4 py-3 shadow-card">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">
              {document.stored_file.original_filename}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-muted-foreground text-xs">
              <span className="rounded-full bg-muted px-2 py-0.5">
                已导入 {documentCount} 个文件 · 共 {pageCount} 页
              </span>
              {documentCount > 1 && (
                <span className="rounded-full bg-muted px-2 py-0.5">
                  第 {documentIndex + 1} 个文件
                </span>
              )}
              {(document.page_count ?? 1) > 1 && (
                <span className="rounded-full bg-muted px-2 py-0.5">
                  PDF 第 {pageNumber} 页
                </span>
              )}
            </div>
            <div
              className={`mt-2 flex items-start gap-1.5 rounded-lg px-3 py-2 text-xs ${
                hasPerspectivePreprocessing(document)
                  ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                  : "bg-amber-500/10 text-amber-700 dark:text-amber-300"
              }`}
            >
              {hasPerspectivePreprocessing(document) ? (
                <CircleCheck className="mt-0.5 size-3.5 shrink-0" />
              ) : (
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
              )}
              <span>{formatPerspectiveStatus(document)}</span>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              disabled={paperPageNumber <= 1}
              onClick={() => {
                setSelectedRegionId(null)
                setDraft(null)
                setPaperPageNumber((value) => Math.max(1, value - 1))
              }}
            >
              <ChevronLeft />
              <span className="sr-only">上一页</span>
            </Button>
            <span className="min-w-20 text-center text-muted-foreground text-xs tabular-nums">
              第 {paperPageNumber} / {pageCount} 页
            </span>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              disabled={paperPageNumber >= pageCount}
              onClick={() => {
                setSelectedRegionId(null)
                setDraft(null)
                setPaperPageNumber((value) => Math.min(pageCount, value + 1))
              }}
            >
              <ChevronRight />
              <span className="sr-only">下一页</span>
            </Button>
          </div>
        </div>
        <Separator />
        <div className="flex flex-wrap items-center gap-x-2 gap-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Select
              value={segmentationEngine}
              onValueChange={(value) =>
                setSegmentationEngine(value as SegmentationEngine)
              }
            >
              <SelectTrigger size="sm" className="w-[150px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="gemini_layout_v1">版面分析</SelectItem>
                <SelectItem value="layout_projection_v0">分栏拆分</SelectItem>
                <SelectItem value="layout_ocr_anchor_v1">文字锚点</SelectItem>
              </SelectContent>
            </Select>
            <Button
              variant="outline"
              size="sm"
              disabled={recognitionOrDetectionPending}
              onClick={detectCurrentPageRegions}
            >
              <Sparkles />
              {candidatesQuery.isFetching ? "检测中" : "检测题目区域"}
            </Button>
            <LoadingButton
              variant="outline"
              size="sm"
              loading={currentPageRecognitionMutation.isPending}
              disabled={recognitionOrDetectionPending}
              onClick={() => currentPageRecognitionMutation.mutate()}
            >
              识别当前页
            </LoadingButton>
            <LoadingButton
              size="sm"
              className="bg-gradient-primary text-white hover:opacity-90"
              loading={recognitionMutation.isPending}
              disabled={recognitionOrDetectionPending}
              onClick={() => recognitionMutation.mutate()}
            >
              <Sparkles />
              识别全卷
            </LoadingButton>
          </div>
          <Separator
            orientation="vertical"
            className="mx-1 hidden h-6 md:block"
          />
          <div className="flex flex-wrap items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setCornerReviewOpen(true)}
            >
              <ScanLine />
              当前文件摆正
            </Button>
            <LoadingButton
              variant="ghost"
              size="sm"
              loading={autoRectifyAllMutation.isPending}
              disabled={recognitionMutation.isPending}
              onClick={() => autoRectifyAllMutation.mutate()}
            >
              <ScanLine />
              全卷摆正
            </LoadingButton>
            <Button
              variant="ghost"
              size="sm"
              disabled={!hasPerspectivePreprocessing(document)}
              onClick={() => setCompareOpen((value) => !value)}
            >
              {compareOpen ? "关闭对比" : "原图/校正图对比"}
            </Button>
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-1">
            {exam && <ExamFilesDialog exam={exam} />}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive"
                >
                  <Trash2 />
                  清除
                  <ChevronDown />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  disabled={
                    !recognitionResponse || currentPageRecognitionCount === 0
                  }
                  onSelect={clearCurrentPageRecognition}
                >
                  清除本页识别
                </DropdownMenuItem>
                <DropdownMenuItem
                  variant="destructive"
                  disabled={!recognitionResponse}
                  onSelect={clearAllRecognition}
                >
                  清除全部识别
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </div>
      <DocumentCornerReviewDialog
        examId={examId}
        document={document}
        open={cornerReviewOpen}
        onOpenChange={setCornerReviewOpen}
        onSaved={handlePerspectiveSaved}
      />
      {compareOpen && hasPerspectivePreprocessing(document) && (
        <div className="xl:col-span-full grid gap-4 rounded-2xl border bg-muted/10 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-semibold">原图 / 校正图对比</div>
              <div className="text-xs text-muted-foreground">
                原图 {document.original_stored_file_id} · 当前校正文件{" "}
                {document.stored_file.id}
              </div>
            </div>
            <div className="text-xs text-muted-foreground">
              左边是上传原图，右边是当前主画布使用的校正页
            </div>
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <div className="grid gap-2">
              <div className="text-xs font-medium text-muted-foreground">
                原图
              </div>
              {sourceImageQuery.isPending || sourceImageQuery.isFetching ? (
                <div className="flex h-64 items-center justify-center rounded-md border text-sm text-muted-foreground">
                  正在加载原图…
                </div>
              ) : sourceUrl ? (
                <img
                  src={sourceUrl}
                  alt="原图"
                  className="max-h-[78vh] w-full rounded-md border bg-black/5 object-contain"
                />
              ) : (
                <div className="flex h-64 items-center justify-center rounded-md border text-sm text-muted-foreground">
                  原图加载失败
                  {sourceImageQuery.isError
                    ? `：${sourceImageQuery.error.message}`
                    : ""}
                </div>
              )}
            </div>
            <div className="grid gap-2">
              <div className="text-xs font-medium text-muted-foreground">
                校正图 / 当前主画布
              </div>
              {displayUrl ? (
                <img
                  src={displayUrl}
                  alt="校正图"
                  className="max-h-[78vh] w-full rounded-md border bg-black/5 object-contain"
                />
              ) : (
                <div className="flex h-64 items-center justify-center rounded-md border text-sm text-muted-foreground">
                  校正图不可用
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      <div
        className="relative self-start overflow-hidden rounded-md border bg-muted/20 xl:col-span-8"
        data-testid="region-marking-canvas"
        ref={canvasRef}
        onPointerDown={(event) => {
          if (event.target !== event.currentTarget) return
          const point = getPoint(event, event.currentTarget)
          setSelectedRegionId(null)
          setInteraction({ mode: "draw", startPoint: point })
          setDraft({ ...point, width: 0, height: 0 })
          event.currentTarget.setPointerCapture(event.pointerId)
        }}
        onPointerMove={(event) => {
          if (!interaction) return
          const point = getPoint(event, event.currentTarget)
          if (interaction.mode === "draw") {
            setDraft(
              normalizeRegion(
                interaction.startPoint.x,
                interaction.startPoint.y,
                point.x,
                point.y,
              ),
            )
            return
          }
          if (!interaction.startRegion) return
          if (interaction.mode === "move") {
            setEditingRegion(
              moveRegion(
                interaction.startRegion,
                point.x - interaction.startPoint.x,
                point.y - interaction.startPoint.y,
              ),
            )
            return
          }
          setEditingRegion(resizeRegion(interaction.startRegion, point))
        }}
        onPointerUp={(event) => {
          if (!interaction) return
          const point = getPoint(event, event.currentTarget)
          if (interaction.mode === "draw") {
            const region = normalizeRegion(
              interaction.startPoint.x,
              interaction.startPoint.y,
              point.x,
              point.y,
            )
            setDraft(
              region.width > 0.01 && region.height > 0.01 ? region : null,
            )
          }
          setInteraction(null)
        }}
      >
        <img
          key={`${document.id}-${document.stored_file.id}-${pageNumber}-${imageVersion}`}
          alt={document.stored_file.original_filename}
          className="pointer-events-none block w-full select-none"
          draggable={false}
          src={displayUrl}
        />
        {pageRegions.map((region) => {
          const isSelected = region.id === selectedRegionId
          const visibleRegion =
            isSelected && editingRegion ? editingRegion : region
          return (
            <div
              key={region.id}
              data-testid={`saved-region-${region.label}`}
              className={`absolute border-2 bg-emerald-500/10 ${
                isSelected ? "border-sky-500" : "border-emerald-500"
              }`}
              style={{
                left: `${visibleRegion.x * 100}%`,
                top: `${visibleRegion.y * 100}%`,
                width: `${visibleRegion.width * 100}%`,
                height: `${visibleRegion.height * 100}%`,
              }}
              onPointerDown={(event) => {
                event.stopPropagation()
                if (!canvasRef.current) return
                const point = getPoint(event, canvasRef.current)
                setSelectedRegionId(region.id)
                setInteraction({
                  mode: "move",
                  regionId: region.id,
                  startPoint: point,
                  startRegion: {
                    x: visibleRegion.x,
                    y: visibleRegion.y,
                    width: visibleRegion.width,
                    height: visibleRegion.height,
                  },
                })
                event.currentTarget.parentElement?.setPointerCapture(
                  event.pointerId,
                )
              }}
            >
              <span className="absolute left-1 top-1 rounded-sm bg-emerald-600 px-1.5 py-0.5 text-xs font-medium text-white">
                {isSelected ? editingLabel || region.label : region.label}
              </span>
              {isSelected && (
                <button
                  type="button"
                  className="absolute -bottom-2 -right-2 size-4 rounded-full border border-background bg-sky-500"
                  onPointerDown={(event) => {
                    event.stopPropagation()
                    if (!canvasRef.current) return
                    const point = getPoint(event, canvasRef.current)
                    setInteraction({
                      mode: "resize",
                      regionId: region.id,
                      startPoint: point,
                      startRegion: {
                        x: visibleRegion.x,
                        y: visibleRegion.y,
                        width: visibleRegion.width,
                        height: visibleRegion.height,
                      },
                    })
                    event.currentTarget.parentElement?.parentElement?.setPointerCapture(
                      event.pointerId,
                    )
                  }}
                >
                  <span className="sr-only">调整区域大小</span>
                </button>
              )}
            </div>
          )
        })}
        {candidateDrafts.map((candidate) => (
          <button
            type="button"
            key={`${candidate.label}-${candidate.x}-${candidate.y}`}
            data-testid={`candidate-region-${candidate.label}`}
            className="absolute border-2 border-dashed border-amber-500 bg-amber-500/10 text-left"
            style={{
              left: `${candidate.x * 100}%`,
              top: `${candidate.y * 100}%`,
              width: `${candidate.width * 100}%`,
              height: `${candidate.height * 100}%`,
            }}
            onClick={(event) => {
              event.stopPropagation()
              selectCandidateDraft(candidate)
            }}
          >
            <span className="absolute left-1 top-1 rounded-sm bg-amber-600 px-1.5 py-0.5 text-xs font-medium text-white">
              {candidate.label}
            </span>
          </button>
        ))}
        {draft && (
          <div
            className="absolute border-2 border-sky-500 bg-sky-500/10"
            style={{
              left: `${draft.x * 100}%`,
              top: `${draft.y * 100}%`,
              width: `${draft.width * 100}%`,
              height: `${draft.height * 100}%`,
            }}
          />
        )}
      </div>

      <aside className="grid content-start gap-4 xl:col-span-4 xl:sticky xl:top-4 xl:max-h-[calc(100vh-2rem)] xl:overflow-y-auto xl:pr-1">
        <section
          className="rounded-2xl border bg-card shadow-card"
          data-testid="current-page-recognition-panel"
        >
          <div className="flex items-start justify-between gap-3 border-b px-4 py-3">
            <div>
              <h2 className="text-sm font-semibold">当前页题目与答案</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                第 {paperPageNumber} 页 · 本页{" "}
                {currentPageAggregatedRecognitionResults.length} 题 · 全卷已汇总{" "}
                {aggregatedRecognitionResults.length} 题
              </p>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-xs"
              disabled={currentPageRecognitionCount === 0}
              onClick={clearCurrentPageRecognition}
            >
              清除本页
            </Button>
          </div>
          {currentPageAggregatedRecognitionResults.length === 0 ? (
            <div className="px-4 py-8 text-center text-muted-foreground text-xs">
              本页还没有识别结果
              <div className="mt-1">点击上方“识别当前页”开始识别</div>
            </div>
          ) : (
            <div className="divide-y">
              {currentPageAggregatedRecognitionResults.map((item) => (
                <article className="grid gap-3 px-4 py-4" key={item.key}>
                  <div className="flex items-center justify-between gap-3">
                    <div className="font-medium text-primary">
                      第{item.questionNumber}题
                      {item.sourceCount > 1 && (
                        <span className="ml-2 text-xs font-normal text-muted-foreground">
                          跨页合并
                        </span>
                      )}
                    </div>
                    {item.confidence != null && item.confidence < 0.8 && (
                      <Tag variant="amber">请核对</Tag>
                    )}
                  </div>
                  <div>
                    <div className="mb-1 text-xs text-muted-foreground">
                      题目
                    </div>
                    <p className="whitespace-pre-wrap text-sm leading-6">
                      {item.question || "未识别"}
                    </p>
                  </div>
                  <div className="rounded-md bg-muted/40 p-3">
                    <div className="mb-1 text-xs text-muted-foreground">
                      学生答案
                    </div>
                    <p className="whitespace-pre-wrap text-sm leading-6">
                      {item.studentAnswer || "未作答"}
                    </p>
                  </div>
                </article>
              ))}
            </div>
          )}
          <div className="grid gap-3 border-t bg-muted/20 px-4 py-4">
            <div className="text-xs text-muted-foreground">
              已识别 {recognizedPageCount} / {pageCount} 页
              {recognizedPageCount < pageCount
                ? `，还需识别 ${pageCount - recognizedPageCount} 页才能进入题目确认。`
                : "，可以复用本次结果进入题目确认，不会重复处理。"}
            </div>
            <LoadingButton
              loading={importRecognitionMutation.isPending}
              disabled={!recognitionReadyForConfirmation}
              onClick={() => importRecognitionMutation.mutate()}
            >
              确认题目并制作标准答案
            </LoadingButton>
          </div>
        </section>
        <button
          type="button"
          className="flex w-full items-center justify-between gap-3 rounded-2xl border bg-card px-4 py-3 text-left shadow-card hover:bg-muted/40"
          onClick={() => setRegionsPanelOpen((value) => !value)}
        >
          <div>
            <div className="text-sm font-semibold">题目位置区域</div>
            <p className="mt-1 text-xs text-muted-foreground">
              标记每道题在卷面上的位置，批改学生答卷时按框逐题裁切。
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2 text-muted-foreground text-xs">
            <span className="tabular-nums">已保存 {pageRegions.length} 个</span>
            <ChevronDown
              className={`transition-transform ${regionsExpanded ? "rotate-180" : ""}`}
            />
          </div>
        </button>
        {regionsExpanded && (
          <>
            <div className="rounded-2xl border bg-card p-4 shadow-card">
              <div className="mb-2 text-sm font-semibold">
                手动新建区域（可选）
              </div>
              {draft ? (
                <div className="grid gap-3">
                  <div className="text-xs text-muted-foreground">
                    蓝色框是待保存的手动草稿，不是 AI 检测结果。
                  </div>
                  <Input
                    value={label}
                    onChange={(event) => setLabel(event.target.value)}
                    placeholder="输入题号，例如 Q1"
                  />
                  <div className="grid grid-cols-2 gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setDraft(null)}
                    >
                      取消草稿
                    </Button>
                    <LoadingButton
                      loading={createMutation.isPending}
                      disabled={draft.width <= 0 || draft.height <= 0}
                      onClick={() => createMutation.mutate(draft)}
                    >
                      保存区域
                    </LoadingButton>
                  </div>
                </div>
              ) : (
                <div className="text-xs text-muted-foreground">
                  需要人工修正时，可在试卷上拖动画框，或点击橙色 AI
                  候选框进行编辑。
                </div>
              )}
            </div>

            <div className="rounded-2xl border bg-card shadow-card">
              <div className="flex items-center justify-between border-b px-4 py-3 text-sm font-semibold">
                <span>AI 候选区域</span>
                <div className="flex items-center gap-2">
                  {candidateDrafts.length > 0 && (
                    <LoadingButton
                      type="button"
                      variant="outline"
                      size="sm"
                      loading={saveCandidatesMutation.isPending}
                      disabled={createMutation.isPending}
                      onClick={() =>
                        saveCandidatesMutation.mutate({
                          candidates: candidateDrafts,
                          documentId: document.id,
                          sourcePageNumber: pageNumber,
                        })
                      }
                    >
                      保存全部候选
                    </LoadingButton>
                  )}
                  {candidatesQuery.data?.elapsed_ms != null && (
                    <span className="text-right text-xs font-normal text-muted-foreground">
                      已完成版面分析 · 转正 {candidatesQuery.data.rotation ?? 0}
                      ° · 总计{" "}
                      {(candidatesQuery.data.elapsed_ms / 1000).toFixed(1)} 秒
                    </span>
                  )}
                </div>
              </div>
              {candidatesQuery.isFetching ? (
                <div className="px-4 py-6 text-center text-muted-foreground text-xs">
                  正在检测页面版面
                </div>
              ) : candidateDrafts.length === 0 ? (
                <div className="px-4 py-6 text-center text-muted-foreground text-xs">
                  点击检测题目区域，加载 AI 建议。
                </div>
              ) : (
                <div className="divide-y">
                  {candidateDrafts.map((candidate) => {
                    const isRefined = candidate.reasons.includes(
                      "horizontal-projection-snap",
                    )
                    return (
                      <button
                        type="button"
                        key={`${candidate.label}-${candidate.x}-${candidate.y}-list`}
                        data-testid={`candidate-list-${candidate.label}`}
                        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-muted/50"
                        onClick={() => selectCandidateDraft(candidate)}
                      >
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium">
                            {candidate.label}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {isRefined
                              ? "已自动校正分隔线"
                              : candidate.source.includes("reference-node")
                                ? "未找到可靠分隔线，请核对"
                                : candidate.confidence < 0.8
                                  ? "题目边界可能不准，请核对"
                                  : "题目边界已识别"}
                          </div>
                        </div>
                        <span className="text-xs text-muted-foreground">
                          采用
                        </span>
                      </button>
                    )
                  })}
                </div>
              )}
            </div>

            <div className="rounded-2xl border bg-card p-4 shadow-card">
              <div className="mb-3 text-sm font-semibold">当前选中区域</div>
              {selectedRegion && editingRegion ? (
                <div className="grid gap-3">
                  <Input
                    data-testid="selected-region-label-input"
                    value={editingLabel}
                    onChange={(event) => setEditingLabel(event.target.value)}
                  />
                  <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                    <span>x {(editingRegion.x * 100).toFixed(1)}%</span>
                    <span>y {(editingRegion.y * 100).toFixed(1)}%</span>
                    <span>w {(editingRegion.width * 100).toFixed(1)}%</span>
                    <span>h {(editingRegion.height * 100).toFixed(1)}%</span>
                  </div>
                  <LoadingButton
                    loading={updateMutation.isPending}
                    onClick={saveSelectedRegion}
                  >
                    <Save />
                    保存修改
                  </LoadingButton>
                </div>
              ) : (
                <div className="text-muted-foreground text-xs">
                  请选择已保存的区域，可移动、缩放或重命名。
                </div>
              )}
            </div>

            <div className="rounded-2xl border bg-card shadow-card">
              <div className="border-b px-4 py-3 text-sm font-semibold">
                已保存区域
              </div>
              {pageRegions.length === 0 ? (
                <div className="px-4 py-6 text-center text-muted-foreground text-xs">
                  在试卷上拖动鼠标，创建第一个题目区域。
                </div>
              ) : (
                <div className="divide-y">
                  {pageRegions.map((region) => (
                    <button
                      type="button"
                      key={region.id}
                      className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-muted/50"
                      onClick={() => setSelectedRegionId(region.id)}
                    >
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium">
                          {region.label}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {(region.width * 100).toFixed(1)}% x{" "}
                          {(region.height * 100).toFixed(1)}%
                        </div>
                      </div>
                      <Button
                        data-testid={`delete-region-${region.label}`}
                        variant="ghost"
                        size="icon-sm"
                        onClick={(event) => {
                          event.stopPropagation()
                          deleteMutation.mutate(region.id)
                        }}
                      >
                        <Trash2 />
                        <span className="sr-only">删除区域</span>
                      </Button>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </aside>
    </div>
  )
}
