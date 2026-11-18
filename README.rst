django-copyist
==============

.. image:: https://img.shields.io/pypi/v/django-copyist.svg
   :target: https://pypi.org/project/django-copyist/
   :alt: PyPI version
.. image:: https://img.shields.io/pypi/pyversions/django-copyist.svg
   :target: https://pypi.org/project/django-copyist/
   :alt: Python versions
.. image:: https://img.shields.io/pypi/frameworkversions/django/django-copyist.svg
   :target: https://pypi.org/project/django-copyist/
   :alt: Django versions
.. image:: https://github.com/abondar/django-copyist/actions/workflows/ci.yml/badge.svg
   :target: https://github.com/abondar/django-copyist/actions/workflows/ci.yml
   :alt: CI
.. image:: https://img.shields.io/pypi/l/django-copyist.svg
   :target: https://github.com/abondar/django-copyist/blob/main/LICENSE.txt
   :alt: License

**Deep-copy Django model instances with all their related objects, in a constant
number of queries.**

django-copyist copies a tree of Django models: a root object, its one-to-many
children, their children, and many-to-many links. You describe the copy in a
declarative config. The models stay untouched. Each level of the tree is read with
``IN`` lookups and written with ``bulk_create``, so the query count depends on the
depth of the tree, not on the number of rows.

On PostgreSQL, a copy of 160 000 rows takes **14 queries and 3.5 s** with
django-copyist, against 400 000 queries and 83 s with per-row cloning
(`benchmark <https://abondar.github.io/django-copyist/benchmark.html>`_).

Install
-------

.. code-block:: console

   pip install django-copyist

Requires Python 3.11+ and Django 5.2, 6.0 or 6.1. CI runs on SQLite and on
PostgreSQL 14, 15 and 18.

Example
-------

Copy a company with its projects and employees, and give the copy a new name:

.. code-block:: python

    from django_copyist import TAKE_FROM_ORIGIN, MakeCopy, ModelCopyConfig, TakeFromInput, run_copy
    from myapp.models import Company, Employee, Project

    COMPANY_COPY_CONFIG = ModelCopyConfig(
        model=Company,
        # Selects the root row: Company.objects.filter(id=input_data["company_id"])
        filter_field_to_input_key={"id": "company_id"},
        field_copy_actions={
            "name": TakeFromInput("new_name"),
            "address": TAKE_FROM_ORIGIN,
            # One-to-many children. The copies point to the new company.
            "projects": MakeCopy(
                ModelCopyConfig(model=Project, field_copy_actions={"name": TAKE_FROM_ORIGIN})
            ),
            "employees": MakeCopy(
                ModelCopyConfig(model=Employee, field_copy_actions={"name": TAKE_FROM_ORIGIN})
            ),
        },
    )

    result = run_copy(
        COMPANY_COPY_CONFIG,
        input_data={"company_id": company.pk, "new_name": "Acme (copy)"},
    )
    assert result.is_copy_successful
    new_company = Company.objects.get(pk=result.copies_of(Company)[str(company.pk)])

Fields that are not in ``field_copy_actions`` get their default value. Every copy runs
in one transaction.

Generate and check configs
--------------------------

Add ``"django_copyist"`` to ``INSTALLED_APPS``, then print a starting config for any
model:

.. code-block:: console

   python manage.py copyist_scaffold myapp.Company --depth 2

Check every config in your test suite. ``check_config`` runs no queries. It reports
unknown fields, required fields that are not copied, unique fields copied from the
origin, unsupported model shapes and more:

.. code-block:: python

    from django_copyist import check_config

    def test_company_copy_config():
        check_config(COMPANY_COPY_CONFIG, raise_on_error=True)

What else it does
-----------------

- **Remap references to existing rows** (``SET_TO_FILTER``): copy tasks into another
  project and point each task at the matching counterpart in that project, found by
  your filter or function.
- **Dry run, then confirm**: when some references have no match, the copy stops and
  returns what did not match and what would be skipped. Show it to the user, then
  run again with ``confirm_write=True``. The copy aborts if the data changed in the
  meantime.
- **Diamond-shaped trees** (``compound_copy_actions``): copy a model that points to
  several copied parents, for example a task that belongs to a copied project and a
  copied employee.
- **Pre-copy and post-copy steps**: delete old data in the target or run your own
  function with the map of origin to copy primary keys.
- **Database alias and batch size**: ``run_copy(..., using="replica_rw", batch_size=500)``.

When to use it
--------------

Use django-copyist to copy whole trees: project templates, tenant data, document
versions, scenario forks. It fits when the tree is large, when copies must point at
rows in a different parent, or when the user must confirm what will be copied.

Use `django-clone <https://github.com/tj-django/django-clone>`_ to duplicate a single
object, for example from a Django admin action. To copy related objects, django-clone
needs its mixin on every model in the tree. It copies row by row, so it calls ``save()``
and fires model signals.

.. list-table::
   :header-rows: 1

   * -
     - django-copyist
     - django-clone
   * - Configuration
     - Config object, models unchanged
     - Mixin and attributes on each model in the tree
   * - Queries for a tree of N rows
     - Constant per tree level
     - Grows with N
   * - Point copies at matching rows of another parent
     - Yes (``SET_TO_FILTER``)
     - No built-in matching
   * - Dry run and confirmation
     - Yes
     - No
   * - Django admin action
     - No
     - Yes
   * - ``save()`` and ``post_save`` signals
     - Not called (``bulk_create``)
     - Called

Limitations
-----------

- Uses ``bulk_create``: ``save()`` and ``pre_save``/``post_save`` signals do not run.
- The database must return primary keys from ``bulk_create`` (PostgreSQL, SQLite
  3.35+, MariaDB), unless the model sets its primary key in Python, for example
  ``UUIDField(default=uuid4)``. MySQL and Oracle are not supported for auto-increment
  keys. MariaDB is not tested in CI.
- No multi-table inheritance, no reverse one-to-one copies, no self-referencing trees
  (a model with a foreign key to itself) yet. ``check_config`` reports all of these.

See `all limitations <https://abondar.github.io/django-copyist/limitations.html>`_.

Documentation
-------------

- `Documentation <https://abondar.github.io/django-copyist/>`_
- `Quickstart <https://abondar.github.io/django-copyist/quickstart.html>`_
- `API reference <https://abondar.github.io/django-copyist/api.html>`_
- `llms.txt <https://abondar.github.io/django-copyist/llms.txt>`_ for AI coding assistants
- `Changelog <https://github.com/abondar/django-copyist/blob/main/CHANGELOG.rst>`_
