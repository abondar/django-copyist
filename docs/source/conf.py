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
copyright = "2024-2026, abondar"
author = "abondar"
release = _META["project"]["version"]

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "enum_tools.autoenum",
    "sphinx_toolbox.more_autodoc.autoprotocol",
    "sphinx_llms_txt",
]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "django": (
        "https://docs.djangoproject.com/en/stable/",
        "https://docs.djangoproject.com/en/stable/_objects/",
    ),
}

html_baseurl = "https://abondar.github.io/django-copyist/"

# llms.txt and llms-full.txt for AI coding assistants, published at the docs root.
# Links point at HTML pages: index.rst only includes README.rst, so its source is empty.
llms_txt_uri_template = "{base_url}{docname}.html"
llms_txt_exclude = ["toc"]
llms_txt_summary = (
    "django-copyist deep-copies Django model instances with their related objects "
    "(one-to-many children, many-to-many links) using a declarative config and "
    "bulk_create, in a number of queries that does not grow with the number of rows. "
    "Public API: `from django_copyist import ModelCopyConfig, MakeCopy, TAKE_FROM_ORIGIN, "
    "TakeFromInput, UpdateToCopied, run_copy, check_config`. Generate a starting config "
    "with `python manage.py copyist_scaffold app.Model` (needs 'django_copyist' in "
    "INSTALLED_APPS). Validate configs with `check_config(config, raise_on_error=True)`. "
    "Result maps are keyed by model class name ('Company'), or by label ('demo.Company') "
    "with `run_copy(..., map_keys=MapKeys.LABEL)`; read them with `result.copies_of(Model)`."
)

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

# autodoc imports the package, which imports Django models through the checks module.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "example.settings")
import django  # noqa: E402

django.setup()
