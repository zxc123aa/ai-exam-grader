import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Save, Sparkles, Trash2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import {
  ApiError,
  type ExamDocumentPublic,
  type ExamRegionCandidate,
  type ExamRegionPublic,
  ExamsService,
  OpenAPI,
} from "@/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
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
}

type SegmentationEngine = "layout_projection_v0" | "layout_ocr_anchor_v1"

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

function getPoint(event: React.PointerEvent<HTMLElement>, target: HTMLElement) {
  const rect = target.getBoundingClientRect()
  return {
    x: clamp((event.clientX - rect.left) / rect.width),
    y: clamp((event.clientY - rect.top) / rect.height),
  }
}

async function fetchPageImageBlob(
  examId: string,
  documentId: string,
  pageNumber: number,
) {
  const token = localStorage.getItem("access_token")
  const base = OpenAPI.BASE || ""
  const response = await fetch(
    `${base}/api/v1/exams/${examId}/files/${documentId}/pages/${pageNumber}/image`,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
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

export default function RegionMarkingCanvas({
  examId,
  document,
  regions,
}: {
  examId: string
  document: ExamDocumentPublic
  regions: ExamRegionPublic[]
}) {
  const pageCount = document.page_count ?? 1
  const [pageNumber, setPageNumber] = useState(1)
  const [label, setLabel] = useState(`Q${regions.length + 1}`)
  const [draft, setDraft] = useState<DraftRegion | null>(null)
  const [interaction, setInteraction] = useState<Interaction | null>(null)
  const [selectedRegionId, setSelectedRegionId] = useState<string | null>(null)
  const [editingRegion, setEditingRegion] = useState<DraftRegion | null>(null)
  const [editingLabel, setEditingLabel] = useState("")
  const [segmentationEngine, setSegmentationEngine] =
    useState<SegmentationEngine>("layout_projection_v0")
  const canvasRef = useRef<HTMLDivElement | null>(null)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryKey = ["exam-regions", examId]

  const blobQuery = useQuery({
    queryKey: ["exam-file-page-image", examId, document.id, pageNumber],
    queryFn: () => fetchPageImageBlob(examId, document.id, pageNumber),
  })
  const candidatesQuery = useQuery({
    queryKey: [
      "exam-region-candidates",
      examId,
      document.id,
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

  useEffect(() => {
    if (!blobQuery.data) {
      setContentUrl(null)
      return
    }
    const url = URL.createObjectURL(blobQuery.data)
    setContentUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [blobQuery.data])

  const createMutation = useMutation({
    mutationFn: (region: DraftRegion) =>
      ExamsService.createExamRegion({
        examId,
        requestBody: {
          label: label.trim() || `Q${regions.length + 1}`,
          region_type: "question",
          page_number: pageNumber,
          ...region,
        },
      }),
    onSuccess: () => {
      showSuccessToast("Region saved")
      setDraft(null)
      setLabel(`Q${regions.length + 2}`)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey })
    },
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
          ...region,
        },
      }),
    onSuccess: () => {
      showSuccessToast("Region updated")
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
      showSuccessToast("Region deleted")
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey })
    },
  })

  const pageRegions = regions.filter(
    (region) => (region.page_number ?? 1) === pageNumber,
  )
  const candidateDrafts: CandidateDraft[] = (
    candidatesQuery.data?.data ?? []
  ).map((candidate: ExamRegionCandidate) => ({
    label: candidate.label,
    confidence: candidate.confidence,
    source: candidate.source,
    x: candidate.x,
    y: candidate.y,
    width: candidate.width,
    height: candidate.height,
  }))
  const selectedRegion = pageRegions.find(
    (region) => region.id === selectedRegionId,
  )

  useEffect(() => {
    setPageNumber((value) => Math.min(Math.max(value, 1), pageCount))
  }, [pageCount])

  useEffect(() => {
    if (!document.id || pageNumber < 1) return
    setSelectedRegionId(null)
    setDraft(null)
    setInteraction(null)
  }, [document.id, pageNumber])

  useEffect(() => {
    if (!candidatesQuery.isError) return
    showErrorToast(candidatesQuery.error.message || "Failed to detect regions")
  }, [candidatesQuery.error, candidatesQuery.isError, showErrorToast])

  useEffect(() => {
    if (!selectedRegion) {
      setEditingRegion(null)
      setEditingLabel("")
      return
    }
    setEditingRegion({
      x: selectedRegion.x,
      y: selectedRegion.y,
      width: selectedRegion.width,
      height: selectedRegion.height,
    })
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

  if (blobQuery.isError) {
    return (
      <div className="rounded-md border p-8 text-sm text-destructive">
        Failed to load image preview.
      </div>
    )
  }

  if (blobQuery.isLoading || !contentUrl) {
    return (
      <div className="rounded-md border p-8 text-sm text-muted-foreground">
        Loading image preview
      </div>
    )
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
      <div className="lg:col-span-2 flex items-center justify-between gap-3 rounded-md border px-4 py-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">
            {document.stored_file.original_filename}
          </div>
          <div className="text-xs text-muted-foreground">
            Page {pageNumber} of {pageCount}
          </div>
        </div>
        <div className="flex items-center gap-2">
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
              <SelectItem value="layout_projection_v0">Projection</SelectItem>
              <SelectItem value="layout_ocr_anchor_v1">OCR anchor</SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="sm"
            disabled={candidatesQuery.isFetching}
            onClick={() => candidatesQuery.refetch()}
          >
            <Sparkles />
            {candidatesQuery.isFetching ? "Detecting" : "Detect regions"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={pageNumber <= 1}
            onClick={() => {
              setSelectedRegionId(null)
              setDraft(null)
              setPageNumber((value) => Math.max(1, value - 1))
            }}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={pageNumber >= pageCount}
            onClick={() => {
              setSelectedRegionId(null)
              setDraft(null)
              setPageNumber((value) => Math.min(pageCount, value + 1))
            }}
          >
            Next
          </Button>
        </div>
      </div>
      <div
        className="relative overflow-hidden rounded-md border bg-muted/20"
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
          alt={document.stored_file.original_filename}
          className="pointer-events-none block w-full select-none"
          draggable={false}
          src={contentUrl}
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
                  <span className="sr-only">Resize region</span>
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

      <aside className="grid content-start gap-4">
        <div className="rounded-md border p-4">
          <div className="mb-3 text-sm font-medium">New region</div>
          <div className="grid gap-3">
            <Input
              value={label}
              onChange={(event) => setLabel(event.target.value)}
              placeholder="Q1"
            />
            <LoadingButton
              loading={createMutation.isPending}
              disabled={!draft || draft.width <= 0 || draft.height <= 0}
              onClick={() => draft && createMutation.mutate(draft)}
            >
              Save Region
            </LoadingButton>
          </div>
        </div>

        <div className="rounded-md border">
          <div className="border-b px-4 py-3 text-sm font-medium">
            Draft candidates
          </div>
          {candidatesQuery.isFetching ? (
            <div className="px-4 py-6 text-sm text-muted-foreground">
              Detecting page layout
            </div>
          ) : candidateDrafts.length === 0 ? (
            <div className="px-4 py-6 text-sm text-muted-foreground">
              Run detection to load suggested question areas.
            </div>
          ) : (
            <div className="divide-y">
              {candidateDrafts.map((candidate) => (
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
                      {(candidate.confidence * 100).toFixed(0)}% ·{" "}
                      {candidate.source}
                    </div>
                  </div>
                  <span className="text-xs text-muted-foreground">Use</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-md border p-4">
          <div className="mb-3 text-sm font-medium">Selected region</div>
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
                Save Changes
              </LoadingButton>
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">
              Select a saved region to move, resize, or rename it.
            </div>
          )}
        </div>

        <div className="rounded-md border">
          <div className="border-b px-4 py-3 text-sm font-medium">
            Saved regions
          </div>
          {pageRegions.length === 0 ? (
            <div className="px-4 py-6 text-sm text-muted-foreground">
              Drag on the paper to create the first question area.
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
                    <span className="sr-only">Delete region</span>
                  </Button>
                </button>
              ))}
            </div>
          )}
        </div>
      </aside>
    </div>
  )
}
