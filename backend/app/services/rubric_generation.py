from __future__ import annotations

import base64
import json

from app.models import StandardAnswer, StandardAnswerStatus, get_datetime_utc
from app.services.grading_rules import validate_rubric
from app.services.vision_grading import call_json_model

RUBRIC_SCHEMA_VERSION = "professional-rubric-v1"


def generate_and_validate_rubric(
    *, image_bytes: bytes, answer: StandardAnswer, question_label: str
) -> StandardAnswer:
    image = base64.b64encode(image_bytes).decode("ascii")
    extracted, vision_model, vision_ms = call_json_model(
        provider="fluxnode_gemini",
        model="gemini-3.5-flash",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"""只读取图片中“{question_label}”对应题块的印刷题干、选项、图表文字，不读取学生答案。识别题型，只返回 JSON：{{"question_text":"完整题干","question_type":"single_choice|multiple_choice|true_false|fill_blank|calculation|proof|short_answer|essay","confidence":0.0}}。""",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image}"},
                    },
                ],
            }
        ],
    )
    question_text = str(extracted.get("question_text", "")).strip()
    question_type = str(extracted.get("question_type", "")).strip()
    prompt = f"""你是资深学科命题与阅卷专家。独立解答题目并生成可执行的专业评分准则。
题目：{question_text}
现有参考答案：{answer.answer_text}
满分：{answer.max_score}
只返回 JSON：{{"canonical_answer":"标准答案","accepted_answers":["等价答案"],"rubric_summary":"总体评分规则","scoring_points":[{{"id":"p1","description":"得分条件","points":1,"required":true,"accepted_evidence":["可接受表述"],"dependencies":[],"partial_credit":[]}}],"deduction_rules":[],"tolerance":{{"absolute":0,"relative":0,"unit_required":false}},"global_rules":{{"error_carry_forward":false,"score_cap":{answer.max_score},"blank_score":0,"unreadable":"review"}}}}。评分点分值之和必须等于满分。"""
    rubric, generator_model, generator_ms = call_json_model(
        provider="pomoai",
        model="gpt-5.6-sol",
        fallback_models=["gpt-5.5"],
        messages=[{"role": "user", "content": prompt}],
    )
    review_prompt = f"""你是独立评分标准审稿人。重新解答题目，检查候选答案与评分准则是否正确、完整、可执行，特别检查评分点合计、等价答案、单位/容差、步骤分和边界情况。发现问题时必须直接修订，不得只提出建议。只返回 JSON：{{"valid":true,"issues":["发现并已修复的问题"],"corrected_rubric":{{"canonical_answer":"修订答案","accepted_answers":[],"rubric_summary":"修订规则","scoring_points":[],"deduction_rules":[],"tolerance":{{}},"global_rules":{{}}}}}}。valid 表示 corrected_rubric 已达到可自动发布标准；corrected_rubric 必须始终返回完整结构，评分点分值之和等于满分。
题目：{question_text}
满分：{answer.max_score}
候选准则：{json.dumps(rubric, ensure_ascii=False)}"""
    review, validator_model, validator_ms = call_json_model(
        provider="pomoai",
        model="gpt-5.6-sol",
        fallback_models=["gpt-5.5"],
        messages=[{"role": "user", "content": review_prompt}],
    )
    corrected = review.get("corrected_rubric")
    if isinstance(corrected, dict):
        rubric = corrected
    answer.question_text = question_text
    answer.question_type = question_type
    answer.answer_text = str(rubric.get("canonical_answer") or answer.answer_text)
    answer.rubric_text = str(rubric.get("rubric_summary") or "")[:8000] or None
    points = rubric.get("scoring_points", [])
    answer.scoring_points = points if isinstance(points, list) else []
    answer.rubric_config = {
        **rubric,
        "schema_version": RUBRIC_SCHEMA_VERSION,
        "vision_confidence": extracted.get("confidence"),
    }
    answer.validation_report = {
        **review,
        "vision_model": vision_model,
        "generator_model": generator_model,
        "validator_model": validator_model,
        "timing_ms": {
            "vision": vision_ms,
            "generation": generator_ms,
            "validation": validator_ms,
        },
    }
    deterministic_errors = validate_rubric(answer)
    answer.validation_report["deterministic_errors"] = deterministic_errors
    answer.validation_report["valid"] = (
        review.get("valid") is True and not deterministic_errors
    )
    if answer.validation_report["valid"]:
        answer.status = StandardAnswerStatus.READY
        answer.source_provider = "pomoai"
        answer.source_model = "gpt-5.6-sol"
        answer.published_at = get_datetime_utc()
    else:
        answer.status = StandardAnswerStatus.DRAFT
    answer.updated_at = get_datetime_utc()
    return answer
