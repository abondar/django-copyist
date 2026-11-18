Generating and checking configs
===============================

Writing a config for a large tree by hand is slow and easy to get wrong.
django-copyist gives you two tools: ``copyist_scaffold`` writes a first version,
and :py:func:`~django_copyist.check_config` finds mistakes before a copy runs.

Generate a config
-----------------

Add the app to your settings. The copy API works without it; only the management
command needs it.

.. code-block:: python

    INSTALLED_APPS = [
        # ...
        "django_copyist",
    ]

Print a config for a model:

.. code-block:: console

    python manage.py copyist_scaffold demo.Company --depth 2

``--depth`` is the number of one-to-many levels to copy with ``MakeCopy``. ``0`` copies
the root row only. Other options:

- ``--name``: name of the generated constant (default ``<MODEL>_COPY_CONFIG``).
- ``--input-key``: ``input_data`` key that selects the root row (default ``<model>_pk``).
- ``--no-check``: do not run ``check_config`` on the result.

The command prints Python code to stdout and the ``check_config`` summary to stderr, so
you can redirect the code into a file:

.. code-block:: console

    python manage.py copyist_scaffold demo.Company --depth 2 > demo/copy_configs.py

For ``demo.Company`` the output is (abridged):

.. code-block:: python

    from django_copyist import MakeCopy, ModelCopyConfig, TAKE_FROM_ORIGIN
    from example.demo.models import Company, Counterpart, Employee, Project, Task


    COMPANY_COPY_CONFIG = ModelCopyConfig(
        model=Company,
        filter_field_to_input_key={"pk": "company_pk"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "address": TAKE_FROM_ORIGIN,
            "projects": MakeCopy(
                ModelCopyConfig(
                    model=Project,
                    field_copy_actions={
                        "name": TAKE_FROM_ORIGIN,
                        "counterparts": MakeCopy(...),
                        "tasks": MakeCopy(
                            ModelCopyConfig(
                                model=Task,
                                field_copy_actions={
                                    "name": TAKE_FROM_ORIGIN,
                                    "description": TAKE_FROM_ORIGIN,
                                    # TODO: Employee is also copied. This keeps the origin
                                    #   reference. To point at the copy, move this model to
                                    #   compound_copy_actions and use UpdateToCopied(Employee).
                                    "assignee": TAKE_FROM_ORIGIN,
                                    # TODO: Counterpart is also copied. ...
                                    "counterparts": TAKE_FROM_ORIGIN,
                                },
                            )
                        ),
                    },
                )
            ),
            "employees": MakeCopy(...),
        },
    )

The generator follows these rules:

- Every concrete field is copied with ``TAKE_FROM_ORIGIN``, except the primary key,
  ``auto_now`` and ``auto_now_add`` fields and generated fields.
- A unique field, and a primary key without a default, gets
  ``TakeFromInput("<model>_<field>")``, because the origin value would violate the
  constraint.
- Forward many-to-many fields are copied with ``TAKE_FROM_ORIGIN``: the copy links to
  the same rows as the origin.
- One-to-many children are copied with ``MakeCopy`` down to ``--depth`` levels.
  A model is copied once: the second path to it becomes a comment.
- A foreign key or many-to-many field that points to a model the config also copies
  gets a ``TODO``. The generated code keeps the origin reference. Decide whether the copy
  should point to the copied row instead, and if so, use ``compound_copy_actions`` and
  :py:func:`~django_copyist.UpdateToCopied`, as in :doc:`quickstart`.
- Many-to-many fields with a custom ``through`` model that has required columns are
  commented out. The ``through`` model is copied as a one-to-many child instead.

You can call the generator from code too: :py:func:`django_copyist.scaffold.scaffold_config`.

Check a config
--------------

:py:func:`~django_copyist.check_config` compares a config with the model metadata. It
runs no queries, so it fits in any unit test:

.. code-block:: python

    from django_copyist import check_config

    from demo.copy_configs import COMPANY_COPY_CONFIG


    def test_company_copy_config():
        check_config(COMPANY_COPY_CONFIG, raise_on_error=True)

It returns a list of :py:class:`~django_copyist.ConfigIssue`. Errors are issues that make
the copy fail or write wrong data. Warnings are issues that are probably not what you
want. ``raise_on_error=True`` raises :py:class:`~django.core.exceptions.ImproperlyConfigured`
if there is at least one error.

.. list-table::
   :header-rows: 1
   :widths: 15 85

   * - Code
     - Meaning
   * - ``copyist.E001``
     - The model has no field or relation with this name.
   * - ``copyist.E002``
     - The action does not fit the field kind, for example ``MakeCopy`` on a forward
       foreign key or ``TAKE_FROM_ORIGIN`` on a reverse relation.
   * - ``copyist.E003``
     - ``reference_to`` or the ``MakeCopy`` model does not match the relation.
   * - ``copyist.E004``
     - A required field without a default is not in ``field_copy_actions``. The insert
       would fail with ``IntegrityError``.
   * - ``copyist.E005``
     - A unique field is copied from the origin.
   * - ``copyist.E006``
     - A many-to-many field uses a ``through`` model with required extra columns.
   * - ``copyist.E007``
     - The model uses multi-table inheritance.
   * - ``copyist.E008``
     - A root config has no ``filter_field_to_input_key``.
   * - ``copyist.E009``
     - The same model is configured more than once.
   * - ``copyist.E010``
     - ``UpdateToCopied`` points to a model that the config never copies.
   * - ``copyist.E011``
     - ``UpdateToCopied`` on a foreign key from a model to itself (a tree). Not
       supported yet.
   * - ``copyist.E012``
     - Two models share a class name while the maps are keyed by class name. Use
       ``CopyistConfig(..., map_keys=MapKeys.LABEL)``.
   * - ``copyist.W001``
     - A field is not copied and gets its default (or ``NULL``, or an empty string).
   * - ``copyist.W002``
     - All fields of a unique constraint are copied from the origin.
   * - ``copyist.W003``
     - A many-to-many field is not copied.
   * - ``copyist.W004``
     - A ``through`` model has extra columns that get their defaults.
   * - ``copyist.W005``
     - A foreign key from a model to itself is copied from the origin: copies keep the
       origin parent.

To silence a warning for a field on purpose, filter by code in your test:

.. code-block:: python

    issues = [
        issue
        for issue in check_config(COMPANY_COPY_CONFIG)
        if (issue.code, issue.field) != ("copyist.W001", "created_by")
    ]
    assert issues == []
