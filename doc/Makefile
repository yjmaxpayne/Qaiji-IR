# Sphinx 文档构建入口（简体中文单语源树）。
# 在仓库根目录使用 make -C doc <目标>，或进入 doc/ 后使用 make <目标>。
# 先激活项目虚拟环境（仓库根目录：source .venv/bin/activate），
# 依赖安装后，也可在仓库根目录使用 uv run --no-sync make -C doc <目标>。

# You can set these variables from the command line, and also
# from the environment for the first two.
SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = source
BUILDDIR      = build

# Put it first so that "make" without argument is like "make help".
help:
	@printf '%s\n' \
	  '用法：make <目标>（在 doc/ 中），或 make -C doc <目标>（在仓库根目录）' \
	  '' \
	  '常用目标：' \
	  '  html         构建并重写全部 HTML 页面：$(BUILDDIR)/html/index.html' \
	  '  doctest      运行文档中显式启用的可执行测试' \
	  '  clean        清空 $(BUILDDIR)/ 中的构建产物' \
	  '  view         构建并打开 HTML，需设置 BROWSER' \
	  '  help         显示本说明及 Sphinx 支持的其他目标（默认目标）' \
	  '' \
	  '示例（在 doc/ 中执行）：' \
	  '  make html' \
	  '  make html SPHINXOPTS="-W --keep-going"  # 警告视为失败，继续收集问题' \
	  '  make html SPHINXOPTS="-E -W --keep-going"  # 重新解析并输出全部页面' \
	  '  make doctest' \
	  '  make view BROWSER=xdg-open              # Linux 桌面预览' \
	  '' \
	  '可覆盖变量：SPHINXBUILD（构建程序）、SPHINXOPTS（参数）、O（附加参数）、' \
	  '            SOURCEDIR（源目录）、BUILDDIR（输出目录）、BROWSER（打开页面的命令）。' \
	  '默认路径相对于 doc/；清理命令保留输出目录本身，不删除源文档。' \
	  '测试通过不代表所有展示性示例均已执行。完整说明见 README.md。' \
	  '' \
	  '以下为 Sphinx 通用目标：'
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

.PHONY: help Makefile view

# Sphinx's incremental writer can leave older pages with stale Furo sidebars
# after a toctree changes. Always rewrite HTML pages using the current environment.
html: Makefile
	@$(SPHINXBUILD) -M html "$(SOURCEDIR)" "$(BUILDDIR)" -a $(SPHINXOPTS) $(O)

# Catch-all target: route all unknown targets to Sphinx using the new
# "make mode" option.  $(O) is meant as a shortcut for $(SPHINXOPTS).
%: Makefile
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

view: html
	$(BROWSER) "$(BUILDDIR)/html/index.html"
