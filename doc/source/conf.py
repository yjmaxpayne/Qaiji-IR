"""Sphinx configuration for the Qaiji-IR documentation."""

from importlib.metadata import metadata

import qaiji

_distribution = metadata("qaiji-ir")

project = _distribution["Name"]
author = _distribution["Author"]
copyright = f"2026, {author}"
release = qaiji.__version__
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

# Logo configuration - displayed in sidebar
html_logo = "_static/logo.png"

html_static_path = ["_static"]
html_show_sourcelink = False


def setup(app):
    app.add_css_file("css/style.css")
