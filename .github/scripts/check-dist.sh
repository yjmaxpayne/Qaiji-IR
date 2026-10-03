#!/usr/bin/env bash
# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
#
# 发布前校验构建产物：<dist> 中恰好有一个 wheel 与一个 sdist，文件名中的版本等于发布标签 vX.Y.Z 去掉 v。
# 给出 <SHA256SUMS> 时，清单列出的文件集合必须与 <dist> 完全相同，且逐个哈希一致——
# 这样发到 PyPI 的文件与 GitHub Release 上已有的制品是同一组字节。
# 用法：check-dist.sh <dist> <tag> [<SHA256SUMS>]。<tag> 可带 refs/tags/ 前缀；只接受正式版标签。
# 退出码：0 通过；1 校验失败；2 用法错误。
set -euo pipefail
[[ $# -ge 2 ]] || { echo "usage: $0 <dist> <tag> [<SHA256SUMS>]" >&2; exit 2; }
dist=$1 tag=${2#refs/tags/} sums=${3:-}
[[ -d $dist ]] || { echo "$dist: not a directory" >&2; exit 2; }
[[ -z $sums || -f $sums ]] || { echo "$sums: not a file" >&2; exit 2; }
[[ -z $sums ]] || sums=$(realpath "$sums")  # 下面会 cd 进 <dist>，相对路径须先解析

[[ $tag =~ ^v([0-9]+\.[0-9]+\.[0-9]+)$ ]] || { echo "only a final release tag vX.Y.Z is published, got '$tag'" >&2; exit 1; }
v=${BASH_REMATCH[1]}
expected=$(printf '%s\n' "qaiji_ir-$v-py3-none-any.whl" "qaiji_ir-$v.tar.gz" | sort)
actual=$(cd "$dist" && ls -A | sort)
if [[ $actual != "$expected" ]]; then
  printf 'dist must contain exactly:\n%s\nfound:\n%s\n' "$expected" "$actual" >&2; exit 1
fi

if [[ -n $sums ]]; then
  # 清单行形如「<哈希>  ./<文件>」或「<哈希>  <文件>」；二进制模式的「*」前缀同样剥掉。
  listed=$(awk '{ name = $2; sub(/^\*/, "", name); sub(/^\.\//, "", name); print name }' "$sums" | sort)
  if [[ $listed != "$expected" ]]; then
    printf 'SHA256SUMS must list exactly the built files:\n%s\nlisted:\n%s\n' "$expected" "$listed" >&2; exit 1
  fi
  (cd "$dist" && sha256sum --check --strict "$sums") >&2 || exit 1
fi
echo "OK: $(echo "$expected" | tr '\n' ' ')match tag $tag${sums:+ and SHA256SUMS}"
