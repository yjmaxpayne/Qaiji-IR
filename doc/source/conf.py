"""Sphinx configuration for the Qaiji-IR documentation."""

import subprocess
from importlib.metadata import metadata
from pathlib import Path

_distribution = metadata("qaiji-ir")
_REPO_ROOT = Path(__file__).resolve().parents[2]
# 首个公开发布的版本号；它被打上 tag 之前，文档显示「<首发版本>.dev」而不是 0.0.0。
_FIRST_RELEASE = "0.1.0"


def _latest_release_tag() -> str | None:
    """返回最近一个发布 tag 的版本号（去掉前缀 v）。

    可编辑安装下 ``qaiji.__version__`` 恒为 0.0.0，不能用来标注文档版本，
    所以直接读 git tag；CI 须以完整历史检出（``fetch-depth: 0``）才能看到 tag。

    Returns:
        形如 ``"0.1.0"`` 的版本号；没有 tag 或不在 git 仓库中时返回 None。
    """
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--match", "v[0-9]*", "--abbrev=0"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip().removeprefix("v") or None


project = _distribution["Name"]
author = _distribution["Author"]
copyright = f"2026, {author}"
# 侧栏左上角通过 _templates/sidebar/brand.html 显示 v{release}。
release = _latest_release_tag() or f"{_FIRST_RELEASE}.dev"
version = release

master_doc = "index"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.doctest",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

language = "zh_CN"
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

autodoc_member_order = "bysource"
autodoc_typehints = "description"
napoleon_google_docstring = True
napoleon_numpy_docstring = False

# -- Intersphinx  --------------------------------------------------------------

intersphinx_mapping: dict[str, tuple[str, str | None]] = {
    "python": ("https://docs.python.org/3", None),
}

# -- Doctest  ------------------------------------------------------------------
#
# Docstring `>>>` examples pulled in via autodoc are illustrative (no testsetup
# context). Setting `doctest_test_doctest_blocks = ''` disables auto-running of
# `>>>` blocks; only explicit `.. doctest::` / `.. testcode::` directives run.

doctest_test_doctest_blocks = ""

# -- Options for HTML output  --------------------------------------------------

html_theme = "furo"
html_title = "Qaiji-IR 文档"
templates_path = ["_templates"]

# Logo configuration - displayed in sidebar
html_logo = "_static/logo.png"

html_static_path = ["_static"]
html_show_sourcelink = False


def setup(app):
    app.add_css_file("css/style.css")
