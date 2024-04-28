# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html
import os
import sys
import tomllib

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information


with open("../../pyproject.toml", "rb") as f:
    _META = tomllib.load(f)

project = "django-copyist"
copyright = "2024, abondar"
author = "abondar"
release = _META["tool"]["poetry"]["version"]

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "enum_tools.autoenum",
    "sphinx_toolbox.more_autodoc.autoprotocol",
]

templates_path = ["_templates"]
exclude_patterns = []

# nitpicky = True

html_favicon = os.path.join("_static", "logo.ico")
html_logo = os.path.join("_static", "logo-no-background.png")

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_book_theme"
html_static_path = ["_static"]

# The master toctree document.
master_doc = "toc"

sys.path.insert(0, os.path.abspath("../.."))
