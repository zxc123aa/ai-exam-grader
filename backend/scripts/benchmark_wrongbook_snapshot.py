"""实测错题本快照的耗时、页渲染次数与存储占用。

方案文档里的存储估算一直是拍的，这个脚本用合成考试量出真实数字，供成本模型与
定价使用。会在库里建临时数据并在结束时清掉。

用法：
    python backend/scripts/benchmark_wrongbook_snapshot.py
    python backend/scripts/benchmark_wrongbook_snapshot.py --students 40 --questions 20
    python backend/scripts/benchmark_wrongbook_snapshot.py --no-cache   # 对照：逐题重渲

注意：会写入数据库和对象存储，不要指向生产环境。
"""

import argparse
import logging
import sys
import time
import uuid
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw  # noqa: E402
from sqlmodel import Session, delete, select  # noqa: E402

from app.core.db import engine  # noqa: E402
from app.models import (  # noqa: E402
    AnnotationGradingStatus,
    ClassGroup,
    Exam,
    ExamQuestion,
    ExamQuestionRegion,
    ExamQuestionStatus,
    ExamRegion,
    Organization,
    ScoreRelease,
    ScoreReleaseItem,
    StoredFile,
    Student,
    StudentSubmission,
    SubmissionAnnotation,
    User,
    UserRole,
    WrongQuestionEntry,
    WrongQuestionSource,
)
from app.services import wrongbook as wrongbook_service  # noqa: E402
from app.services.object_storage import (  # noqa: E402
    delete_storage_key,
    materialize_storage_key,
    put_storage_bytes,
)

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger("wrongbook-benchmark")


def build_page_png(width: int = 1240, height: int = 1754) -> bytes:
    """A4 @150dpi 量级的合成答卷页，带手写风格线条以贴近真实压缩率。"""
    image = Image.new("RGB", (width, height), color=(252, 252, 250))
    draw = ImageDraw.Draw(image)
    for index in range(24):
        top = round(height * (0.03 + index * 0.04))
        draw.rectangle(
            (round(width * 0.06), top, round(width * 0.94), top + round(height * 0.03)),
            outline=(210, 210, 205),
        )
        draw.line(
            (
                round(width * 0.1),
                top + round(height * 0.02),
                round(width * (0.3 + (index % 5) * 0.12)),
                top + round(height * 0.008),
            ),
            fill=(40, 60, 130),
            width=3,
        )
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def load_page_bytes(page_file: str | None, as_pdf: bool) -> tuple[bytes, str, str]:
    """返回 (页面字节, content_type, 文件名)。

    默认用合成页；给了 `--page-file` 就用真实卷面照片，压缩率才有参考价值。
    """
    if page_file:
        source = Path(page_file)
        with Image.open(source) as image:
            rgb = image.convert("RGB")
            buffer = BytesIO()
            if as_pdf:
                rgb.save(buffer, format="PDF")
                return buffer.getvalue(), "application/pdf", "answer.pdf"
            rgb.save(buffer, format="JPEG", quality=92)
            return buffer.getvalue(), "image/jpeg", "answer.jpg"
    png = build_page_png()
    if as_pdf:
        with Image.open(BytesIO(png)) as image:
            buffer = BytesIO()
            image.convert("RGB").save(buffer, format="PDF")
            return buffer.getvalue(), "application/pdf", "answer.pdf"
    return png, "image/png", "answer.png"


def seed(
    session: Session,
    *,
    students: int,
    questions: int,
    page_bytes: bytes,
    content_type: str,
    filename: str,
) -> tuple[Exam, list[str]]:
    tag = uuid.uuid4().hex[:8]
    org = Organization(name=f"基准学校-{tag}", code=f"bench-{tag}")
    session.add(org)
    session.flush()
    owner = User(
        email=f"bench-{tag}@example.com",
        hashed_password="x",
        role=UserRole.SCHOOL_OWNER,
        org_id=org.id,
    )
    session.add(owner)
    session.flush()
    exam = Exam(
        title=f"基准考试-{tag}", subject="物理", owner_id=owner.id, org_id=org.id
    )
    session.add(exam)
    session.flush()

    regions: list[ExamRegion] = []
    for index in range(questions):
        region = ExamRegion(
            exam_id=exam.id,
            label=f"第{index + 1}题",
            page_number=1,
            x=0.06,
            y=0.03 + (index % 20) * 0.045,
            width=0.88,
            height=0.04,
        )
        session.add(region)
        session.flush()
        question = ExamQuestion(
            exam_id=exam.id,
            question_key=str(index + 1),
            label=region.label,
            question_text=f"第 {index + 1} 题题干。" * 8,
            question_type="calculation",
            status=ExamQuestionStatus.CONFIRMED,
        )
        session.add(question)
        session.flush()
        session.add(
            ExamQuestionRegion(question_id=question.id, exam_region_id=region.id)
        )
        regions.append(region)

    class_group = ClassGroup(name=f"基准班-{tag}", org_id=org.id, owner_id=owner.id)
    session.add(class_group)
    session.flush()

    storage_keys: list[str] = []
    for student_index in range(students):
        student = Student(class_id=class_group.id, name=f"考生{student_index + 1:03d}")
        session.add(student)
        session.flush()
        storage_key = f"bench/{tag}/{student_index}-{filename}"
        put_storage_bytes(storage_key, page_bytes)
        storage_keys.append(storage_key)
        stored_file = StoredFile(
            original_filename=filename,
            content_type=content_type,
            storage_key=storage_key,
            size_bytes=len(page_bytes),
            sha256=uuid.uuid4().hex * 2,
            uploaded_by_id=owner.id,
        )
        session.add(stored_file)
        session.flush()
        submission = StudentSubmission(
            exam_id=exam.id,
            stored_file_id=stored_file.id,
            student_id=student.id,
            student_name=student.name,
            class_name=class_group.name,
        )
        session.add(submission)
        session.flush()
        for index, region in enumerate(regions):
            # 约 60% 的题判为错题，接近真实卷面
            wrong = index % 5 < 3
            annotation = SubmissionAnnotation(
                submission_id=submission.id,
                exam_region_id=region.id,
                label=region.label,
                page_number=1,
                x=region.x,
                y=region.y,
                width=region.width,
                height=region.height,
                score=6 if wrong else 10,
                max_score=10,
                comment="过程不完整" if wrong else None,
                ocr_text="P=W/t",
                score_source="human",
                grading_status=AnnotationGradingStatus.SUCCEEDED,
            )
            annotation.grading_evidence = [
                {"point": "写出公式", "matched": True, "points": 4},
                {"point": "代入数据", "matched": not wrong, "points": 6},
            ]
            session.add(annotation)
    session.commit()
    return exam, storage_keys


def publish(session: Session, exam: Exam) -> ScoreRelease:
    release = ScoreRelease(exam_id=exam.id, version=1)
    session.add(release)
    session.flush()
    annotations = session.exec(
        select(SubmissionAnnotation, StudentSubmission)
        .join(
            StudentSubmission,
            SubmissionAnnotation.submission_id == StudentSubmission.id,
        )
        .where(StudentSubmission.exam_id == exam.id)
    ).all()
    for annotation, _submission in annotations:
        session.add(
            ScoreReleaseItem(
                release_id=release.id,
                submission_id=annotation.submission_id,
                annotation_id=annotation.id,
                label=annotation.label,
                score=annotation.score,
                max_score=annotation.max_score,
                comment=annotation.comment,
                source="human",
            )
        )
    session.commit()
    session.refresh(release)
    return release


def measure(session: Session, exam: Exam, release: ScoreRelease) -> dict:
    started = time.perf_counter()
    created = wrongbook_service.snapshot_release(session, release.id)
    elapsed = time.perf_counter() - started

    entries = session.exec(
        select(WrongQuestionEntry)
        .join(
            WrongQuestionSource,
            WrongQuestionEntry.source_id == WrongQuestionSource.id,
        )
        .where(WrongQuestionSource.exam_id == exam.id)
    ).all()
    image_bytes = 0
    image_count = 0
    for entry in entries:
        if not entry.image_storage_key:
            continue
        try:
            path = materialize_storage_key(entry.image_storage_key)
        except Exception:
            continue
        if path.exists():
            image_bytes += path.stat().st_size
            image_count += 1
    return {
        "entries": created,
        "elapsed_seconds": round(elapsed, 2),
        "images": image_count,
        "image_bytes": image_bytes,
    }


def cleanup(session: Session, exam: Exam, storage_keys: list[str]) -> None:
    sources = session.exec(
        select(WrongQuestionSource).where(WrongQuestionSource.exam_id == exam.id)
    ).all()
    for source in sources:
        entries = session.exec(
            select(WrongQuestionEntry).where(WrongQuestionEntry.source_id == source.id)
        ).all()
        for entry in entries:
            if entry.image_storage_key:
                try:
                    delete_storage_key(entry.image_storage_key)
                except Exception:
                    pass
            session.delete(entry)
        session.delete(source)
    session.commit()
    org_id = exam.org_id
    releases = session.exec(
        select(ScoreRelease).where(ScoreRelease.exam_id == exam.id)
    ).all()
    for release in releases:
        session.execute(
            delete(ScoreReleaseItem).where(ScoreReleaseItem.release_id == release.id)
        )
        session.delete(release)
    session.commit()
    session.delete(exam)
    session.commit()
    session.execute(
        delete(Student).where(
            Student.class_id.in_(  # type: ignore[attr-defined]
                select(ClassGroup.id).where(ClassGroup.org_id == org_id)
            )
        )
    )
    session.execute(delete(ClassGroup).where(ClassGroup.org_id == org_id))
    # StoredFile 引用上传者，必须在删用户之前清掉
    session.execute(
        delete(StoredFile).where(
            StoredFile.uploaded_by_id.in_(  # type: ignore[attr-defined]
                select(User.id).where(User.org_id == org_id)
            )
        )
    )
    session.execute(delete(User).where(User.org_id == org_id))
    session.commit()
    organization = session.get(Organization, org_id)
    if organization:
        session.delete(organization)
        session.commit()
    for key in storage_keys:
        try:
            delete_storage_key(key)
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="错题本快照基准")
    parser.add_argument("--students", type=int, default=40)
    parser.add_argument("--questions", type=int, default=20)
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="对照组：禁用按页缓存，逐题重新渲染",
    )
    parser.add_argument("--keep", action="store_true", help="不清理数据，便于排查")
    parser.add_argument(
        "--page-file",
        default=None,
        help="用真实卷面图作为答卷页，例如 materials/physics/1.jpg",
    )
    parser.add_argument(
        "--pdf", action="store_true", help="答卷存为 PDF（渲染更贵，更接近扫描件）"
    )
    args = parser.parse_args()

    if args.no_cache:
        original_get = wrongbook_service.PageImageCache.get

        def uncached_get(self, *, stored_file, page_number):  # type: ignore[no-untyped-def]
            self.render_count += 1
            return wrongbook_service.render_stored_file_page_image(
                stored_file=stored_file, page_number=page_number
            )

        wrongbook_service.PageImageCache.get = uncached_get  # type: ignore[method-assign]
        wrongbook_service.PageImageCache.close = lambda self: None  # type: ignore[method-assign]
        del original_get

    renders = {"count": 0}
    original_render = wrongbook_service.render_stored_file_page_image

    def counting_render(**kwargs):  # type: ignore[no-untyped-def]
        renders["count"] += 1
        return original_render(**kwargs)

    wrongbook_service.render_stored_file_page_image = counting_render  # type: ignore[assignment]

    page_bytes, content_type, filename = load_page_bytes(args.page_file, args.pdf)
    with Session(engine) as session:
        exam, storage_keys = seed(
            session,
            students=args.students,
            questions=args.questions,
            page_bytes=page_bytes,
            content_type=content_type,
            filename=filename,
        )
        release = publish(session, exam)
        result = measure(session, exam, release)
        result["page_renders"] = renders["count"]
        per_student = result["image_bytes"] / args.students if args.students else 0
        print(  # noqa: T201
            "\n".join(
                [
                    f"页面来源         {args.page_file or '合成页'}"
                    f"{'（PDF）' if args.pdf else ''}",
                    f"考生数           {args.students}",
                    f"题目数           {args.questions}",
                    f"错题本条目       {result['entries']}",
                    f"留存答题图       {result['images']} 张",
                    f"页渲染次数       {result['page_renders']}",
                    f"快照耗时         {result['elapsed_seconds']} 秒",
                    f"图片总体积       {result['image_bytes'] / 1024:.0f} KiB",
                    f"每生每场         {per_student / 1024:.0f} KiB",
                    f"每生每年(10场)   {per_student * 10 / 1024 / 1024:.1f} MiB",
                ]
            )
        )
        if not args.keep:
            cleanup(session, exam, storage_keys)


if __name__ == "__main__":
    main()
