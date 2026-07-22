from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def load_gate_module() -> ModuleType:
    script = Path(__file__).resolve().parents[3] / "scripts" / "fast_reconstruction_gate.py"
    spec = importlib.util.spec_from_file_location("fast_reconstruction_gate", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fast_reconstruction_gate"] = module
    spec.loader.exec_module(module)
    return module


def candidate_question(number: int, body: str = "候选题干") -> str:
    return f"## 第 {number} 题（1 分）\n\n{body}\n"


def trusted_question(number: int, body: str = "可信题干") -> str:
    return f"### {number}.\n{body}\n"


def write_candidate_round(base: Path) -> Path:
    round_dir = base / "round_001"
    round_dir.mkdir()

    question_bodies = {
        7: (
            "2024年4月25日，中国长征二号F遥火箭搭载神舟十八号载人飞船将3名航天员顺利送入太空。\n"
            "在运载火箭加速升空的过程中，关于火箭动能和势能变化的说法正确的是（　）"
        ),
        12: "我们用吸管“吸”饮料时，饮料是在________作用下被“吸”入口中的。",
        21: "骑行时受到的阻力为总重的0.03倍（ρ=1.0×10³kg/m³，g=10N/kg），求：",
        22: "手环瞬间弹出一个体积为3.5×10⁻²m³的气囊。",
    }
    reconstructed = "\n".join(
        candidate_question(number, question_bodies.get(number, f"候选第 {number} 题"))
        for number in range(1, 23)
    )
    (round_dir / "reconstructed_exam.md").write_text(reconstructed, encoding="utf-8")

    scores = [3] * 10 + [4] * 7 + [4, 8, 8, 10, 12]
    questions = [
        {"question_number": number, "score": score}
        for number, score in zip(range(1, 23), scores, strict=True)
    ]
    (round_dir / "question_index.json").write_text(
        json.dumps({"metadata": {}, "questions": questions}, ensure_ascii=False),
        encoding="utf-8",
    )
    (round_dir / "ocr_raw_blocks.json").write_text(
        json.dumps({"metadata": {}, "blocks": []}), encoding="utf-8"
    )
    (round_dir / "qc_report.md").write_text("状态：PARTIAL\n", encoding="utf-8")
    (round_dir / "uncertainties.md").write_text("## U001\n\n## U002\n", encoding="utf-8")
    (round_dir / "diff_against_previous.md").write_text("# Diff\n", encoding="utf-8")
    return round_dir


def write_trusted_markdown(base: Path) -> Path:
    trusted = base / "trusted.md"
    question_bodies = {
        7: (
            "2024 年 4 月 25 日，中国长征二号 F 遥十八运载火箭搭载神舟十八号载人飞船，"
            "将 3 名航天员顺利送入太空。在运载火箭加速升空的过程中，"
            "关于航天员动能和势能变化的说法正确的是（　　）"
        ),
        12: "夏日里用吸管“吸”饮料时，饮料是在 ＿＿＿＿ 作用下被“吸”入口中的。",
        21: "骑行时受到的阻力为总重的 0.03 倍（ρ水 = 1.0×10³ kg/m³，g = 10 N/Kg），求：",
        22: "手环瞬间弹出一个体积为 3.5×10⁻² m³ 的气囊。",
    }
    trusted.write_text(
        "\n".join(
            trusted_question(number, question_bodies.get(number, f"可信第 {number} 题"))
            for number in range(1, 23)
        ),
        encoding="utf-8",
    )
    return trusted


def test_run_gate_emits_targeted_anomaly_queue(tmp_path: Path) -> None:
    gate = load_gate_module()
    candidate_round = write_candidate_round(tmp_path)
    trusted = write_trusted_markdown(tmp_path)
    output_dir = tmp_path / "gate"

    result = gate.run_gate(candidate_round, trusted, output_dir)

    assert result["checks"]["contract_files_present"] is True
    assert result["checks"]["candidate_questions"] == list(range(1, 23))
    assert result["checks"]["trusted_questions"] == list(range(1, 23))
    assert result["checks"]["score_total"] == 100

    codes = {item["code"] for item in result["anomalies"]}
    assert "Q7_ROCKET_MODEL" in codes
    assert "Q7_SUBJECT" in codes
    assert "Q12_DRINK_PHRASE" in codes
    assert "Q21_RHO_WATER" in codes
    assert "Q22_AIRBAG_VOLUME" not in codes

    assert (output_dir / "deterministic_checks.json").exists()
    assert (output_dir / "anomaly_queue.md").exists()
    assert (output_dir / "agent_review_prompt.md").exists()
    summary = (output_dir / "gate_summary.md").read_text(encoding="utf-8")
    assert "Agents should review only `anomaly_queue.md`" in summary
