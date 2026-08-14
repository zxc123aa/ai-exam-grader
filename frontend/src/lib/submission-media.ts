import { ApiError, OpenAPI } from "@/client"

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("access_token")
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function fetchBlob(url: string, apiUrl: string, errorMessage: string) {
  const response = await fetch(`${OpenAPI.BASE || ""}${url}`, {
    headers: authHeaders(),
  })
  if (!response.ok) {
    throw new ApiError(
      { method: "GET", url: apiUrl },
      {
        url: response.url,
        ok: response.ok,
        status: response.status,
        statusText: response.statusText,
        body: await response.text(),
      },
      errorMessage,
    )
  }
  return response.blob()
}

export async function fetchSubmissionPageImageBlob(
  examId: string,
  submissionId: string,
  pageNumber: number,
) {
  return fetchBlob(
    `/api/v1/exams/${examId}/submissions/${submissionId}/pages/${pageNumber}/image`,
    "/api/v1/exams/{exam_id}/submissions/{submission_id}/pages/{page_number}/image",
    "Failed to load student submission preview",
  )
}

export async function fetchSubmissionAnnotationCropBlob(
  examId: string,
  submissionId: string,
  annotationId: string,
) {
  return fetchBlob(
    `/api/v1/exams/${examId}/submissions/${submissionId}/annotations/${annotationId}/crop`,
    "/api/v1/exams/{exam_id}/submissions/{submission_id}/annotations/{annotation_id}/crop",
    "Failed to load annotation crop",
  )
}

/** 错题本条目自带的答题图，学生本人可取，不依赖考试权限。 */
export async function fetchWrongbookEntryImageBlob(entryId: string) {
  return fetchBlob(
    `/api/v1/students/me/wrongbook/entries/${entryId}/image`,
    "/api/v1/students/me/wrongbook/entries/{entry_id}/image",
    "Failed to load wrongbook entry image",
  )
}

export async function fetchSubmissionRegionCropBlob(
  examId: string,
  submissionId: string,
  regionId: string,
) {
  return fetchBlob(
    `/api/v1/exams/${examId}/submissions/${submissionId}/regions/${regionId}/crop`,
    "/api/v1/exams/{exam_id}/submissions/{submission_id}/regions/{region_id}/crop",
    "Failed to load region crop",
  )
}
