"""识别回归一键脚本：拿 golden 截图跑当前视觉链路，输出逐张结果和硬案例断言。

用法：
  cd backend && uv run python ../scripts/recognition_regression.py
  # 或指定 golden 目录/输出目录
  cd backend && uv run python ../scripts/recognition_regression.py \
      --golden ../data/golden/recognition-report --tag v0.6.4

产物：
  <golden>/runs/<tag>.jsonl   每张的识别原文
  汇总打印：调用失败数、硬案例 PASS/FAIL、与上一基线的文本差异
退出码非零 = 有调用失败或硬案例 FAIL，可接 CI/发布门禁。
"""

import argparse
import base64
import json
import sys
import time
from pathlib import Path

from sqlmodel import Session

from app.core.db import engine
from app.services.system_config import get_grading_defaults
from app.services.vision_grading import call_json_model

PROMPT = (
    "读出图中试卷内容：题目（含选项）和学生手写作答"
    "（原样照抄，写错不纠正；没写答案填「未作答」；绘图作答填「绘图作答」）。"
    '只返回JSON：{"items":[{"question_text":"...","student_answer":"..."}]}'
)


def run_one(defaults: dict, image_b64: str) -> tuple[list[dict], str, int]:
    parsed, model, ms = call_json_model(
        provider=defaults["vision_provider"],
        model=defaults["vision_model"],
        fallback_models=[str(x) for x in defaults["vision_fallback_models"]],
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                ],
            }
        ],
    )
    return parsed.get("items") or [], model, ms


def flatten(items: list[dict]) -> str:
    return "\n".join(
        f"{it.get('question_text', '')}\n{it.get('student_answer', '')}"
        for it in items
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--golden",
        default=str(Path(__file__).parent.parent / "data/golden/recognition-report"),
    )
    parser.add_argument("--tag", default=time.strftime("%Y%m%d-%H%M"))
    parser.add_argument(
        "--baseline",
        default="baseline-3.7.jsonl",
        help="对比的历史结果文件（在 golden 目录下，存在才对比）",
    )
    args = parser.parse_args()
    golden = Path(args.golden)
    manifest = json.loads((golden / "manifest.json").read_text())

    runs_dir = golden / "runs"
    runs_dir.mkdir(exist_ok=True)
    out_path = runs_dir / f"{args.tag}.jsonl"
    out = out_path.open("w")

    results = []
    failures = 0
    with Session(engine) as session:
        defaults = get_grading_defaults(session)
        print(f"视觉链路：{defaults['vision_model']} → {defaults['vision_fallback_models']}")
        for item in manifest:
            image = base64.b64encode((golden / item["file"]).read_bytes()).decode()
            t0 = time.time()
            try:
                items, model, ms = run_one(defaults, image)
                rec = {
                    "file": item["file"],
                    "issue": item.get("issue", ""),
                    "model": model,
                    "items": items,
                    "error": None,
                }
            except Exception as exc:  # noqa: BLE001 回归要记失败而不是中断
                failures += 1
                rec = {
                    "file": item["file"],
                    "issue": item.get("issue", ""),
                    "model": None,
                    "items": [],
                    "error": str(exc)[:200],
                }
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            results.append(rec)
            print(f"{item['file']}  {round(time.time() - t0)}s", flush=True)

    # 硬案例断言
    checks = []
    for item, rec in zip(manifest, results, strict=True):
        expect = item.get("expect")
        if not expect:
            continue
        text = flatten(rec["items"])
        ok = all(s in text for s in expect.get("must_contain", [])) and not any(
            s in text for s in expect.get("must_not_contain", [])
        )
        checks.append((item["file"], item.get("issue", ""), ok))

    # 与历史基线对比（文本变化）
    diffs = []
    baseline_path = golden / args.baseline
    if baseline_path.exists():
        old = {
            json.loads(line)["file"]: flatten(json.loads(line)["items"])
            for line in baseline_path.read_text().splitlines()
            if line.strip()
        }
        for rec in results:
            old_text = old.get(rec["file"])
            new_text = flatten(rec["items"])
            if old_text is not None and old_text != new_text:
                diffs.append(rec["file"])

    print("\n===== 回归汇总 =====")
    print(f"总数 {len(results)} | 调用失败 {failures}")
    for file, issue, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {file}（{issue}）")
    if baseline_path.exists():
        print(f"与基线 {baseline_path.name} 文本有差异的：{len(diffs)} 张 {diffs[:8]}")
    print(f"结果已存 {out_path}")

    hard_failed = sum(1 for _, _, ok in checks if not ok)
    return 1 if (failures or hard_failed) else 0


if __name__ == "__main__":
    sys.exit(main())
