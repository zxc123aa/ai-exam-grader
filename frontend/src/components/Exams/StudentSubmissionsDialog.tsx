import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  CheckCircle2,
  Eye,
  FileUp,
  Loader2,
  ScanLine,
  SquarePen,
  Users,
  XCircle,
} from "lucide-react"
import { useEffect, useState } from "react"

import {
  ApiError,
  type ExamPublic,
  ExamsService,
  OpenAPI,
  type StudentSubmissionPublic,
} from "@/client"
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
import { handleError } from "@/utils"

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function formatStatus(status?: string) {
  return (status || "registration_pending").replace(/_/g, " ")
}

function formatQuality(quality?: number | null) {
  if (quality == null) return null
  return `${Math.round(quality * 100)}%`
}

async function fetchSubmissionPageImageBlob(
  examId: string,
  submissionId: string,
  pageNumber: number,
) {
  const token = localStorage.getItem("access_token")
  const base = OpenAPI.BASE || ""
  const response = await fetch(
    `${base}/api/v1/exams/${examId}/submissions/${submissionId}/pages/${pageNumber}/image`,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    },
  )
  if (!response.ok) {
    throw new ApiError(
      {
        method: "GET",
        url: "/api/v1/exams/{exam_id}/submissions/{submission_id}/pages/{page_number}/image",
      },
      {
        url: response.url,
        ok: response.ok,
        status: response.status,
        statusText: response.statusText,
        body: await response.text(),
      },
      "Failed to load student submission preview",
    )
  }
  return response.blob()
}

function SubmissionPreview({
  examId,
  submission,
}: {
  examId: string
  submission: StudentSubmissionPublic
}) {
  const pageCount = submission.page_count ?? 1
  const [pageNumber, setPageNumber] = useState(1)
  const [contentUrl, setContentUrl] = useState<string | null>(null)
  const { data, isLoading, isError } = useQuery({
    queryKey: [
      "student-submission-page-image",
      examId,
      submission.id,
      pageNumber,
    ],
    queryFn: () =>
      fetchSubmissionPageImageBlob(examId, submission.id, pageNumber),
  })
  const regionsQuery = useQuery({
    queryKey: [
      "student-submission-template-regions",
      examId,
      submission.id,
      pageNumber,
    ],
    queryFn: () =>
      ExamsService.readStudentSubmissionTemplateRegions({
        examId,
        submissionId: submission.id,
        pageNumber,
      }),
  })

  useEffect(() => {
    if (!data) {
      setContentUrl(null)
      return
    }
    const url = URL.createObjectURL(data)
    setContentUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [data])

  useEffect(() => {
    setPageNumber((value) => Math.min(Math.max(value, 1), pageCount))
  }, [pageCount])

  return (
    <div className="grid gap-3 rounded-md border p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">
            {submission.stored_file.original_filename}
          </div>
          <div className="text-xs text-muted-foreground">
            Page {pageNumber} of {pageCount}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={pageNumber <= 1}
            onClick={() => setPageNumber((value) => Math.max(1, value - 1))}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={pageNumber >= pageCount}
            onClick={() =>
              setPageNumber((value) => Math.min(pageCount, value + 1))
            }
          >
            Next
          </Button>
        </div>
      </div>
      {isError ? (
        <div className="rounded-md border p-6 text-sm text-destructive">
          Failed to load submission preview.
        </div>
      ) : isLoading || !contentUrl ? (
        <div className="flex items-center gap-2 rounded-md border p-6 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Loading preview
        </div>
      ) : (
        <div
          className="relative overflow-hidden rounded-md border bg-muted/20"
          data-testid="submission-preview-canvas"
        >
          <img
            alt={submission.stored_file.original_filename}
            className="block w-full select-none"
            draggable={false}
            src={contentUrl}
          />
          {(regionsQuery.data?.data ?? []).map((region) => (
            <div
              key={region.id}
              className="absolute border-2 border-sky-500 bg-sky-500/10"
              data-testid={`submission-overlay-region-${region.label}`}
              style={{
                left: `${region.x * 100}%`,
                top: `${region.y * 100}%`,
                width: `${region.width * 100}%`,
                height: `${region.height * 100}%`,
              }}
            >
              <span className="absolute left-1 top-1 rounded-sm bg-sky-600 px-1.5 py-0.5 text-xs font-medium text-white">
                {region.label}
              </span>
            </div>
          ))}
        </div>
      )}
      {!regionsQuery.isLoading &&
        !regionsQuery.isError &&
        (regionsQuery.data?.data ?? []).length === 0 && (
          <div className="text-xs text-muted-foreground">
            No template regions on this page yet.
          </div>
        )}
    </div>
  )
}

export default function StudentSubmissionsDialog({
  exam,
}: {
  exam: ExamPublic
}) {
  const [isOpen, setIsOpen] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [scanPhotoFile, setScanPhotoFile] = useState<File | null>(null)
  const [studentName, setStudentName] = useState("")
  const [studentIdentifier, setStudentIdentifier] = useState("")
  const [previewSubmission, setPreviewSubmission] =
    useState<StudentSubmissionPublic | null>(null)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryKey = ["student-submissions", exam.id]

  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () => ExamsService.readStudentSubmissions({ examId: exam.id }),
    enabled: isOpen,
  })

  const mutation = useMutation({
    mutationFn: (file: File) =>
      ExamsService.uploadStudentSubmission({
        examId: exam.id,
        formData: {
          file: file as unknown as string,
          student_name: studentName.trim() || undefined,
          student_identifier: studentIdentifier.trim() || undefined,
        },
      }),
    onSuccess: () => {
      showSuccessToast("Student submission uploaded")
      setSelectedFile(null)
      setStudentName("")
      setStudentIdentifier("")
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey })
    },
  })

  const scanMutation = useMutation({
    mutationFn: (file: File) =>
      ExamsService.preprocessStudentSubmissionPhoto({
        examId: exam.id,
        formData: {
          file: file as unknown as string,
          student_name: studentName.trim() || undefined,
          student_identifier: studentIdentifier.trim() || undefined,
        },
      }),
    onSuccess: () => {
      showSuccessToast("Scan photo converted")
      setScanPhotoFile(null)
      setStudentName("")
      setStudentIdentifier("")
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey })
    },
  })

  const registrationMutation = useMutation({
    mutationFn: ({
      submission,
      registrationStatus,
    }: {
      submission: StudentSubmissionPublic
      registrationStatus: "manual_confirmed" | "failed"
    }) =>
      ExamsService.updateStudentSubmissionRegistration({
        examId: exam.id,
        submissionId: submission.id,
        requestBody:
          registrationStatus === "manual_confirmed"
            ? {
                registration_status: "manual_confirmed",
                registration_quality: 1,
                registration_notes:
                  "Teacher confirmed same-layout registration",
                registration_homography: {
                  matrix: [
                    [1, 0, 0],
                    [0, 1, 0],
                    [0, 0, 1],
                  ],
                },
              }
            : {
                registration_status: "failed",
                registration_quality: 0,
                registration_notes: "Teacher marked registration as failed",
              },
      }),
    onSuccess: () => {
      showSuccessToast("Registration status updated")
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey })
    },
  })

  const submissions = data?.data ?? []

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Users />
          Submissions
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>{exam.title} submissions</DialogTitle>
          <DialogDescription>
            Upload student answer PDFs or images for template registration.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-5">
          <div className="grid gap-3 rounded-md border p-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <Input
                data-testid="submission-student-name-input"
                value={studentName}
                onChange={(event) => setStudentName(event.target.value)}
                placeholder="Student name"
              />
              <Input
                data-testid="submission-student-identifier-input"
                value={studentIdentifier}
                onChange={(event) => setStudentIdentifier(event.target.value)}
                placeholder="Student ID"
              />
            </div>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <Input
                data-testid="submission-file-input"
                type="file"
                accept=".pdf,image/png,image/jpeg"
                onChange={(event) =>
                  setSelectedFile(event.target.files?.[0] ?? null)
                }
              />
              <LoadingButton
                data-testid="submission-upload-button"
                type="button"
                loading={mutation.isPending}
                disabled={!selectedFile}
                onClick={() => selectedFile && mutation.mutate(selectedFile)}
                className="sm:w-32"
              >
                <FileUp />
                Upload
              </LoadingButton>
            </div>
            <div className="flex flex-col gap-3 border-t pt-3 sm:flex-row sm:items-center">
              <Input
                data-testid="submission-scan-photo-input"
                type="file"
                accept=".jpg,.jpeg,.png,image/png,image/jpeg"
                onChange={(event) =>
                  setScanPhotoFile(event.target.files?.[0] ?? null)
                }
              />
              <LoadingButton
                data-testid="submission-scan-photo-button"
                type="button"
                loading={scanMutation.isPending}
                disabled={!scanPhotoFile}
                onClick={() =>
                  scanPhotoFile && scanMutation.mutate(scanPhotoFile)
                }
                className="sm:w-44"
              >
                <ScanLine />
                Convert photo
              </LoadingButton>
            </div>
          </div>

          <div className="rounded-md border">
            <div className="flex items-center justify-between border-b px-4 py-3">
              <span className="text-sm font-medium">Student submissions</span>
              <Badge variant="secondary">{submissions.length}</Badge>
            </div>
            {isLoading ? (
              <div className="flex items-center gap-2 px-4 py-8 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                Loading submissions
              </div>
            ) : submissions.length === 0 ? (
              <div className="px-4 py-8 text-sm text-muted-foreground">
                No student submissions uploaded for this exam yet.
              </div>
            ) : (
              <div className="divide-y">
                {submissions.map((submission) => (
                  <div
                    key={submission.id}
                    className="grid gap-3 px-4 py-3 lg:grid-cols-[1fr_auto] lg:items-center"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">
                        {submission.student_name || "Unnamed student"}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {submission.student_identifier || "No student ID"} ·{" "}
                        {submission.stored_file.original_filename} ·{" "}
                        {formatBytes(submission.stored_file.size_bytes)} ·{" "}
                        {submission.page_count} page
                        {submission.page_count === 1 ? "" : "s"}
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                      <Badge variant="outline" className="capitalize">
                        {formatStatus(submission.status)}
                      </Badge>
                      <Badge variant="secondary" className="capitalize">
                        {formatStatus(submission.registration_status)}
                        {formatQuality(submission.registration_quality)
                          ? ` · ${formatQuality(submission.registration_quality)}`
                          : ""}
                      </Badge>
                      <Button
                        data-testid={`confirm-registration-${submission.id}`}
                        variant="outline"
                        size="sm"
                        disabled={registrationMutation.isPending}
                        onClick={() =>
                          registrationMutation.mutate({
                            submission,
                            registrationStatus: "manual_confirmed",
                          })
                        }
                      >
                        <CheckCircle2 />
                        Confirm
                      </Button>
                      <Button
                        data-testid={`fail-registration-${submission.id}`}
                        variant="outline"
                        size="sm"
                        disabled={registrationMutation.isPending}
                        onClick={() =>
                          registrationMutation.mutate({
                            submission,
                            registrationStatus: "failed",
                          })
                        }
                      >
                        <XCircle />
                        Fail
                      </Button>
                      <Button
                        data-testid={`submission-preview-button-${submission.id}`}
                        variant="outline"
                        size="sm"
                        onClick={() => setPreviewSubmission(submission)}
                      >
                        <Eye />
                        Preview
                      </Button>
                      <Button variant="outline" size="sm" asChild>
                        <Link
                          to="/exams/$examId/submissions/$submissionId/review"
                          params={{
                            examId: exam.id,
                            submissionId: submission.id,
                          }}
                        >
                          <SquarePen />
                          Review
                        </Link>
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {previewSubmission && (
            <SubmissionPreview
              examId={exam.id}
              submission={previewSubmission}
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
