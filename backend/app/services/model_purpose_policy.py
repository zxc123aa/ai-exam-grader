"""Authoritative model-family rules for model-backed business functions."""

TRADITIONAL_IMAGE_PURPOSES = {
    "photo_preprocessing",
    "scan_preprocessing",
}

PURE_VISION_PURPOSES = {
    "region_detection",
    "question_recognition",
    "score_structure_recognition",
    "answer_document_parsing",
    "rubric_question_recognition",
    "answer_recognition",
    "answer_extraction",
}

REASONING_PURPOSES = {
    "answer_preparation",
    "rubric_generation",
    "rubric_validation",
    "subjective_grading",
}

MODEL_ROUTED_PURPOSES = PURE_VISION_PURPOSES | REASONING_PURPOSES

VISUAL_MODEL_PREFIXES = ("gemini-3.6-flash", "gemini-3.5-flash")
REASONING_MODEL_PREFIXES = ("gpt-5.6-sol", "gpt-5.6-terra", "kimi-")

VISION_DEFAULT_PREFERENCE = ("gemini-3.6-flash", "gemini-3.5-flash")
REASONING_DEFAULT_PREFERENCE = (
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "kimi-k2.7-code",
    "kimi-k3",
)


def model_allowed_for_purpose(*, purpose: str, canonical_model: str) -> bool:
    model = canonical_model.casefold().replace(":", "/").rsplit("/", 1)[-1]
    if purpose in PURE_VISION_PURPOSES:
        return model.startswith(VISUAL_MODEL_PREFIXES)
    if purpose in REASONING_PURPOSES:
        return model.startswith(REASONING_MODEL_PREFIXES)
    return purpose not in TRADITIONAL_IMAGE_PURPOSES


def purpose_kind(purpose: str) -> str | None:
    if purpose in PURE_VISION_PURPOSES:
        return "vision"
    if purpose in REASONING_PURPOSES:
        return "reasoning"
    if purpose in TRADITIONAL_IMAGE_PURPOSES:
        return "traditional"
    return None
