# 文档构建

本目录包含 Qaiji-IR 的简体中文 Sphinx 手册（单语源树 `source/`）。通过
[Makefile](Makefile) 可以构建 HTML、运行文档测试和清理生成文件。本说明文件
介绍构建流程，位于 Sphinx 源目录之外。

## 环境准备

除非另有说明，以下命令均在 Linux 的 Bash 中执行，起始位置为**仓库根目录**。
需要 GNU Make、uv 和 Python 3.12–3.14；Python 要求见
[`.python-version`](../.python-version) 与 [`pyproject.toml`](../pyproject.toml)。
安装依赖需要访问配置的软件包索引。首次构建时，Sphinx 还会下载外部 Python
交叉引用索引（intersphinx）。

首次检出仓库后，安装项目与文档依赖：

```bash
uv sync --group docs
source .venv/bin/activate
```

检查当前环境中的工具：

```bash
python --version
python -m sphinx --version
make --version
make -C doc help
```

依赖安装完成后，也可用以下方式调用项目环境，无需提前激活或同步依赖：

```bash
uv run --no-sync make -C doc help
```

## 源文件与输出

下表中的路径均相对于 `doc/`。

| 内容 | 位置 |
|---|---|
| 源目录 | `source/` |
| Sphinx 配置 | `source/conf.py` |
| HTML 入口 | `build/html/index.html` |
| 文档解析缓存 | `build/doctrees/` |
| 文档测试报告 | `build/doctest/output.txt` |
| 共享徽章片段 | `_includes/badges.rst` |

接口页面通过 Sphinx 的自动文档功能（`autodoc`）导入项目模块，因此构建需要
可正常运行的项目环境。
首页通过 `.. include:: ../_includes/badges.rst` 引入仅在 HTML 中显示的徽章；
其顺序、图片地址、替代文本应与仓库根目录的 [README.md](../README.md) 同步。
调整依赖要求时，应对照 [`pyproject.toml`](../pyproject.toml) 更新版本徽章。

## 构建 HTML

```bash
make -C doc html
```

该目标每次重写全部 HTML 页面，避免新增目录项后旧页面保留过期侧栏。例如新增
`native-schedule` 后，重新执行此命令会同步更新 `conventions.html` 的左侧目录。
它仍会复用已解析的 Sphinx 环境。

审查或自动化任务可将警告视为失败，同时继续收集诊断信息：

```bash
make -C doc html SPHINXOPTS="-W --keep-going"
```

重新解析全部源文件并重写所有输出页面：

```bash
make -C doc html SPHINXOPTS="-E -W --keep-going"
```

`-E` 忽略已保存的 Sphinx 环境；HTML 目标已内置 `-a`，会输出全部页面。
该重建不会删除输出目录中已废弃的文件；需要干净的输出树时使用下面的清理命令。

## 运行文档测试

```bash
make -C doc doctest SPHINXOPTS="-W --keep-going"
```

配置中设置了 `doctest_test_doctest_blocks = ""`：只有显式的 `doctest` 和
`testcode` 分组会执行，普通展示性代码块与自动发现的 `>>>` 示例不会执行。
请在 `output.txt` 中核对报告的测试数与失败数。HTML 构建成功本身不能证明
示例可以正确执行。

## 本地预览

在配置了 `xdg-open` 的 Linux 桌面环境中，以下目标构建手册并打开其 HTML 入口：

```bash
make -C doc view BROWSER=xdg-open
```

`BROWSER` 在 Makefile 中没有默认值。在没有桌面集成的终端中，
可以改用本地服务器提供已构建文件：

```bash
python -m http.server 8000 --bind 127.0.0.1 --directory doc/build
```

保持服务器运行，在同一台机器的浏览器中打开 `http://127.0.0.1:8000/html/`。
使用 Ctrl+C 停止服务器；8000 端口被占用时另选端口。该命令只提供现有输出，
不会构建手册。

## 清理生成文件

```bash
make -C doc clean
```

`clean` 清空整个 `build/` 目录；Sphinx 会保留所选构建目录本身。源文件不受
影响。

## 在 doc/ 内工作与覆盖路径

如果命令行的当前目录已经是 `doc/`，省略 `-C doc`：

```bash
make help
make html SPHINXOPTS="-W --keep-going"
```

Make 变量可以在命令行上覆盖：

| 变量 | 默认值 | 用途 |
|---|---|---|
| `SPHINXBUILD` | `sphinx-build` | Sphinx 命令；也可用 `python -m sphinx` |
| `SPHINXOPTS` | 空 | Sphinx 参数 |
| `O` | 空 | 追加在 `SPHINXOPTS` 之后的附加参数 |
| `SOURCEDIR` | `source` | 源目录 |
| `BUILDDIR` | `build` | 输出根目录 |
| `BROWSER` | 未设置 | `view` 目标使用的命令 |

相对的源与输出路径均从 `doc/` 解析，使用 `make -C doc` 时也是如此。从仓库
根目录用当前 Python 解释器构建到独立的输出树：

```bash
make -C doc html BUILDDIR=build-check SPHINXBUILD="python -m sphinx" SPHINXOPTS="-W --keep-going"
```

生成的入口是 `doc/build-check/html/index.html`。后续预览与清理命令使用相同的
`BUILDDIR` 覆盖；HTTP 服务器的 `--directory` 也指向该输出根。

## 故障排查

| 现象 | 检查项 |
|---|---|
| `make: command not found` | GNU Make 需要在 Python 依赖之外单独安装。命令是 `make`。 |
| `sphinx-build: command not found` | 激活已准备的环境，或设置 `SPHINXBUILD="python -m sphinx"` 并使用其解释器。 |
| `No module named sphinx` 或自动文档导入错误 | 检查当前环境包含项目本体与 `docs` 依赖组。 |
| 严格构建在下载交叉引用索引时失败 | 检查 Sphinx 报告的索引 URL 的网络访问，然后重试构建。 |
| 引用损坏或意外的过期页面 | 阅读 Sphinx 的完整诊断信息，修复源文件后用 `-E` 重建；已删除页面残留时清理输出树。 |
| 预览目标无法打开浏览器 | 在桌面会话中设置 `BROWSER`，或使用本地 HTTP 服务器。 |

## 命令审计

于 2026-09-28 使用 Python 3.13.15 与 Sphinx 9.1.0 复核。在已准备好的项目
环境中检查了干净构建、重复 HTML 构建、文档测试、自定义输出路径和生成页面的
侧栏链接。此前已检查清理边界与本地 HTTP 响应；桌面预览命令路由未测试
（未启动图形浏览器）。
