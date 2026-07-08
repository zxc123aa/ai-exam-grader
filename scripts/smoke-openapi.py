# ruff: noqa: T201

import sys

from app.main import app

REQUIRED_PATHS = {
    "/api/v1/exams/",
    "/api/v1/exams/{exam_id}",
    "/api/v1/exams/{exam_id}/files",
    "/api/v1/exams/{exam_id}/files/{document_id}/content",
    "/api/v1/exams/{exam_id}/files/{document_id}/pages/{page_number}/image",
    "/api/v1/exams/{exam_id}/files/{document_id}/region-candidates",
    "/api/v1/exams/{exam_id}/answers",
    "/api/v1/exams/{exam_id}/answers/{answer_id}",
    "/api/v1/exams/{exam_id}/regions",
    "/api/v1/exams/{exam_id}/regions/{region_id}",
    "/api/v1/exams/{exam_id}/submissions",
    "/api/v1/exams/{exam_id}/submissions/preprocess-photo",
    "/api/v1/exams/{exam_id}/submissions/{submission_id}",
    "/api/v1/exams/{exam_id}/submissions/{submission_id}/registration",
    "/api/v1/exams/{exam_id}/submissions/{submission_id}/processing-tasks",
    "/api/v1/exams/{exam_id}/submissions/{submission_id}/pages/{page_number}/image",
    "/api/v1/exams/{exam_id}/submissions/{submission_id}/regions",
    "/api/v1/exams/{exam_id}/submissions/{submission_id}/regions/{region_id}/crop",
    "/api/v1/exams/{exam_id}/submissions/{submission_id}/annotations",
    "/api/v1/exams/{exam_id}/submissions/{submission_id}/annotations/{annotation_id}",
    "/api/v1/exams/{exam_id}/submissions/{submission_id}/annotations/{annotation_id}/crop",
    "/api/v1/files/upload",
    "/api/v1/tasks/test",
    "/api/v1/tasks/{task_id}",
    "/api/v1/utils/health",
}


def main() -> int:
    schema = app.openapi()
    paths = set(schema.get("paths", {}))
    missing = sorted(REQUIRED_PATHS - paths)
    if missing:
        print("Missing OpenAPI paths:")
        for path in missing:
            print(f"- {path}")
        return 1

    print("OpenAPI smoke check passed.")
    print(f"Project: {schema.get('info', {}).get('title')}")
    print(f"Checked paths: {len(REQUIRED_PATHS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
