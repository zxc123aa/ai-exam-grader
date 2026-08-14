#!/usr/bin/env bash
# 为默认分支开启分支保护，把 CI 从「提示」变成「阻断」。
#
# 前置条件：
#   1. 仓库是私有仓库时，GitHub 只在 Pro/Team/Enterprise 计划上提供分支保护。
#      免费计划的私有仓库会返回 403 "Upgrade to GitHub Pro or make this
#      repository public"。注意本仓库历史提交中存在带真实值的 .env，
#      不要为了免费而改成 public。
#   2. 需要仓库管理员身份的 token，并具备 Administration: write 权限。
#      细粒度 PAT 勾选 Repository permissions -> Administration: Read and write，
#      或经典 PAT 勾选 repo。Cursor / GitHub App 的安装 token 没有这个权限。
#
# 用法：
#   GH_TOKEN=<admin-token> ./scripts/setup-branch-protection.sh            # 应用保护
#   GH_TOKEN=<admin-token> ./scripts/setup-branch-protection.sh --show     # 只看当前状态
#   REQUIRE_REVIEWS=1 GH_TOKEN=... ./scripts/setup-branch-protection.sh    # 额外要求 1 个 review
#
# 默认策略：要求四个 CI 检查通过且分支与 main 保持最新，不强制 review，
# 不对管理员生效（留一条应急直推通道）。团队协作后建议打开 REQUIRE_REVIEWS
# 并把 ENFORCE_ADMINS 设为 1。

set -euo pipefail

REPO="${REPO:-zxc123aa/ai-exam-grader}"
BRANCH="${BRANCH:-main}"
CONTEXTS="${CONTEXTS:-lint-backend test-backend test-frontend zizmor}"
REQUIRE_REVIEWS="${REQUIRE_REVIEWS:-0}"
ENFORCE_ADMINS="${ENFORCE_ADMINS:-0}"

if ! command -v gh >/dev/null 2>&1; then
  echo "需要 GitHub CLI：https://cli.github.com/" >&2
  exit 1
fi

api() { gh api -H "Accept: application/vnd.github+json" "$@"; }

show_state() {
  echo "== $REPO 分支 $BRANCH 当前保护状态 =="
  if ! api "repos/$REPO/branches/$BRANCH/protection" 2>/tmp/bp.err; then
    if grep -q "Upgrade to GitHub Pro" /tmp/bp.err; then
      echo "不可用：私有仓库需要 GitHub Pro/Team/Enterprise 计划。"
    elif grep -q "Branch not protected" /tmp/bp.err; then
      echo "未开启保护。"
    else
      cat /tmp/bp.err >&2
    fi
    return 1
  fi
}

echo "== 最近一次提交实际上报的检查名（用于核对 contexts）=="
api "repos/$REPO/commits/$BRANCH/check-runs" --jq '.check_runs[].name' 2>/dev/null | sort -u || echo "（读不到，可能是权限不足或该提交还没跑过 CI）"

if [ "${1:-}" = "--show" ]; then
  show_state || true
  exit 0
fi

# GitHub 的 PUT 接口要求一次性提交完整策略，未列出的字段会被重置，
# 因此这里显式给出每一项，而不是做增量更新。
contexts_json=$(printf '%s\n' $CONTEXTS | jq -R . | jq -sc .)
if [ "$REQUIRE_REVIEWS" = "1" ]; then
  reviews_json='{"required_approving_review_count":1,"dismiss_stale_reviews":true,"require_code_owner_reviews":false}'
else
  reviews_json='null'
fi
enforce_admins_json=$([ "$ENFORCE_ADMINS" = "1" ] && echo true || echo false)

payload=$(jq -nc \
  --argjson contexts "$contexts_json" \
  --argjson reviews "$reviews_json" \
  --argjson enforce_admins "$enforce_admins_json" \
  '{
     required_status_checks: {strict: true, contexts: $contexts},
     enforce_admins: $enforce_admins,
     required_pull_request_reviews: $reviews,
     restrictions: null,
     required_linear_history: false,
     allow_force_pushes: false,
     allow_deletions: false,
     required_conversation_resolution: true
   }')

echo "== 即将应用的策略 =="
echo "$payload" | jq .

if ! echo "$payload" | api --method PUT "repos/$REPO/branches/$BRANCH/protection" --input - >/tmp/bp.out 2>/tmp/bp.err; then
  echo "失败：" >&2
  if grep -q "Upgrade to GitHub Pro" /tmp/bp.err; then
    echo "  私有仓库的分支保护需要 GitHub Pro/Team/Enterprise 计划。" >&2
    echo "  升级后重跑本脚本即可，不需要改动代码。" >&2
  elif grep -q "Resource not accessible by integration" /tmp/bp.err; then
    echo "  token 缺少 Administration: write 权限。GitHub App 安装 token 不行，" >&2
    echo "  需要仓库管理员本人的 PAT。" >&2
  else
    cat /tmp/bp.err >&2
  fi
  exit 1
fi

echo "== 应用成功，当前状态 =="
show_state
