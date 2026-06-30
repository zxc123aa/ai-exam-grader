# Third Party Licenses

This document tracks direct dependencies and referenced projects for AI Exam Grader. Keep it updated when adding or removing packages.

## Direct Foundation

| Project | Use | License |
| --- | --- | --- |
| Full Stack FastAPI Template | Application scaffold | MIT |
| FastAPI | Backend API framework | MIT |
| SQLModel | ORM and data models | MIT |
| PostgreSQL | Primary database | PostgreSQL License |
| Redis | Worker broker | BSD-3-Clause |
| Dramatiq | Background task processing | LGPL-3.0 |
| React | Web UI framework | MIT |
| Vite | Frontend build tooling | MIT |
| TanStack Router/Query/Table | Routing, API state and tables | MIT |
| Tailwind CSS | Frontend styling | MIT |
| shadcn/ui generated components | UI component source pattern | MIT |
| lucide-react | Icons | ISC |
| pypdfium2 | PDF rendering | Apache-2.0 |
| Pillow | PDF page image encoding | HPND |

## Planned Direct Dependencies

| Project | Planned Use | License |
| --- | --- | --- |
| React Konva | Template editor and annotation canvas | MIT |
| PaddleOCR | OCR and text coordinates | Apache-2.0 |
| OpenCV | Page detection, correction and registration | Apache-2.0 |

## Reference Only

| Project | Reference Use | License Notes |
| --- | --- | --- |
| OMRChecker | Filled bubble recognition approach | Reference only; do not copy code without license review |
| MakeACopy | Mobile scanning workflow ideas | Reference only; review license before reuse |

## Policy

- Prefer permissive licenses for direct dependencies.
- Do not copy source from reference projects unless the license is reviewed and compatible.
- Record dependency name, usage and license before adding production code.
