.. _changelog:

=========
Changelog
=========


0.2
===

0.2.0
-----

Breaking changes
~~~~~~~~~~~~~~~~

- Dropped support for Django 4.2 (end of life). Supported: Django 5.2, 6.0 and 6.1.
- A config in which two models share a class name now raises ``ImproperlyConfigured``
  before the copy starts. In 0.1 such a copy mixed the models in the result maps and
  wrote wrong references. Pass ``map_keys=MapKeys.LABEL`` to copy it.

- ``TAKE_FROM_ORIGIN`` and ``TAKE_FROM_INPUT`` on a foreign key now store the key column
  in ``CopyIntent.copy_data`` (``"project_id": 1`` instead of ``"project": <Project>``).
  This matters only if a postcopy function reads ``copy_data``.
- Callback protocols (``IgnoreFunc``, ``SetToFilterFunc``, ``DataPreparationFunc``,
  ``PostcopyFunc``) take keyword-only arguments, which is how the engine always called
  them. Type checkers now accept callbacks written as ``def f(**kwargs)``.
- Removed ``Copyist.get_copyist_for_request``. It referenced attributes that did not
  exist and failed on every call.

Added
~~~~~

- Public API in the package root: ``from django_copyist import ModelCopyConfig, run_copy, ...``.
  Names in ``django_copyist.__all__`` follow semantic versioning.
- ``run_copy()``: build the request and run the copy in one call.
- ``CopyResult.copies_of(Model)``: origin to copy primary keys for one model.
- ``MapKeys`` and ``map_keys`` on ``CopyistConfig`` and ``run_copy()``. The default,
  ``MapKeys.MODEL_NAME``, keeps the 0.1 keys (``"Company"``). ``MapKeys.LABEL`` keys the
  maps by model label (``"demo.Company"``), so models with the same class name in
  different apps can be copied together.
- ``TakeFromInput(key)`` shortcut.
- ``check_config()``: static checks of a config against model metadata, with stable
  issue codes (``copyist.E001`` to ``copyist.E012``, ``copyist.W001`` to ``copyist.W005``).
- ``manage.py copyist_scaffold app.Model``: prints a starting config for a model tree.
  Needs ``"django_copyist"`` in ``INSTALLED_APPS``. Also available as
  ``django_copyist.scaffold.scaffold_config()``.
- ``using`` and ``batch_size`` options on ``CopyRequest`` and ``run_copy()``.
- ``TAKE_FROM_INPUT`` on a foreign key accepts a primary key value as well as a model
  instance.
- Clear ``NotSupportedError`` when the database does not return primary keys from
  ``bulk_create`` (MySQL, Oracle).
- ``py.typed`` marker: type checkers now use the package annotations. The package
  passes ``mypy --strict`` with django-stubs, and CI checks it together with sample
  user code (``example/typing_examples.py``).
- Support for Django 6.0 and 6.1 and Python 3.15.
- Benchmark against django-clone and a naive loop (``benchmarks/``, results in the docs).
- ``llms.txt`` and ``llms-full.txt`` in the documentation for AI coding assistants.

Fixed
~~~~~

- Many-to-many fields with ``TAKE_FROM_ORIGIN`` or ``SET_TO_FILTER`` failed with
  ``IntegrityError`` when more than one row was copied.
- ``TAKE_FROM_ORIGIN`` on a foreign key ran one query per row to load the related
  object. It now copies the key column.
- Models whose primary key is not named ``id`` failed with ``FieldError`` in
  ``SET_TO_FILTER`` and ignore conditions.
- ``compound_copy_actions`` with several nullable ``UpdateToCopied`` foreign keys used the
  wrong model's ids and skipped rows.
- ``0``, ``False`` and ``""`` in ``input_data`` were rejected as missing filter values.
- Models without an ``objects`` manager failed. The engine uses the default manager now.
- Children of rows skipped by an unmatched ``SET_TO_FILTER`` value failed with
  ``KeyError`` under ``confirm_write=True``. They are skipped with their parent now.
- Copies with more rows per level than the database parameter limit failed on SQLite
  with "too many SQL variables". Long ``IN`` lookups are split into chunks.

0.1
===

0.1.3
-----
- Improved docs

0.1.1
-----

- Specified python >=3.11

0.1.0
-----

- Initial release
