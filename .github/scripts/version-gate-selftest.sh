#!/usr/bin/env bash
# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
#
# 版本守门自测：已提交的 poetry-dynamic-versioning 配置必须拒绝错误的版本来源，并对合法 tag 给出确切版本。
# 在一次性 clone 里造临时 tag 后构建 wheel；临时 tag 只存在于该 clone，退出时连同 clone 一起删除。
# 期望失败的用例同时核对构建后端的报错文本：构建必须因该用例的原因失败，而不是因为别的错误。
# 用法：version-gate-selftest.sh <repo>。<repo> 须带完整历史（CI 的 checkout 要 fetch-depth: 0）。
# 退出码：0 全部通过；1 有用例未通过；2 无法搭建临时仓库。
set -u
export PYTHONDONTWRITEBYTECODE=1
SRC=$(cd "${1:?usage: $0 <repo>}" && pwd) || exit 2
W=$(mktemp -d -t version-gate.XXXXXX) || exit 2
trap 'rm -rf "$W"' EXIT
R=$W/repo
# 显式关掉签名与钩子：开发机上的全局 git 配置不能让临时提交或打 tag 失败。
g() { git -C "$R" -c user.name=gate -c user.email=gate@localhost -c commit.gpgSign=false -c tag.gpgSign=false \
  -c core.hooksPath=/dev/null "$@"; }

git -c advice.detachedHead=false clone -q --no-hardlinks "$SRC" "$R" || exit 2
# 被测提交之上叠一个空提交，HEAD 与 HEAD~1 供叠 tag；本地分支让浅克隆不依赖源仓库的分支名或 detached 状态。
g commit -q --allow-empty -m "gate: tip" && g switch -q -c gate-tip || exit 2
echo "commit under test: $(git -C "$SRC" rev-parse HEAD)"

fails=0
retag() {  # retag name@rev ...：先删掉全部 tag，再按参数重建
  g tag -l | xargs -r git -C "$R" tag -d >/dev/null
  local t
  for t in "$@"; do g tag "${t%@*}" "${t#*@}" || exit 2; done
}
shallow() {  # shallow <dir> <ref>：从临时仓库做深度为 1 的克隆；失败时目录不存在，check 会判该用例未通过
  git -c advice.detachedHead=false clone -q --depth 1 --branch "$2" "file://$R" "$1"
}
check() {  # check <name> <dir> fail <报错文本 ERE> | check <name> <dir> ok <确切版本>
  local out rc ver verdict=FAIL
  out=$(cd "$2" && uv build --wheel -o "$W/dist-$1" 2>&1)
  rc=$?
  ver=$(find "$W/dist-$1" -name '*.whl' 2>/dev/null | sed -E 's/.*qaiji_ir-([^-]+)-.*/\1/')
  if [ "$3" = fail ]; then
    [ "$rc" -ne 0 ] && grep -qE "$4" <<<"$out" && verdict=PASS
  elif [ "$rc" -eq 0 ] && [ "$ver" = "$4" ]; then
    verdict=PASS
  fi
  [ "$verdict" = PASS ] || fails=$((fails + 1))
  printf '%s %-27s want=%s rc=%s version=%s | %s\n' "$verdict" "$1" "$3:$4" "$rc" "${ver:-<none>}" \
    "$(grep -E '^[A-Za-z]*Error: |^error: |cd: ' <<<"$out" | head -1 | cut -c1-120)"
}

retag
check no-tag "$R" fail 'No tags available'
retag v0.1.0rc1@HEAD
check non-matching-tag "$R" fail 'did not match'
retag v0.1.0@HEAD~1 v0.1.1rc1@HEAD
check non-matching-over-matching "$R" fail 'did not match the latest tag'
retag v0.1.0@HEAD
shallow "$W/shallow-at-tag" v0.1.0
check shallow-tag-at-head "$W/shallow-at-tag" fail 'shallow repository'
retag v0.1.0@HEAD~1
shallow "$W/shallow-tip" gate-tip
check shallow-tag-behind-head "$W/shallow-tip" fail 'shallow repository'
retag v0.1.0@HEAD
check tag-at-head "$R" ok 0.1.0
retag v0.1.0@HEAD~1
check tag-behind-head "$R" ok "0.1.0.post1.dev0+$(g rev-parse --short HEAD)"

echo "fails=$fails"
[ "$fails" -eq 0 ]
