Limitations
===========

django-copyist trades some of Django's per-row behaviour for speed. Check this list
before you adopt it. :py:func:`~django_copyist.check_config` reports the items marked
with an error code.

Writes
------

- **No** ``save()`` **and no model signals.** Copies are inserted with
  ``bulk_create``. ``Model.save()``, ``pre_save`` and ``post_save`` do not run, and
  neither does ``m2m_changed`` for copied links. Put side effects in a
  :py:class:`~django_copyist.PostcopyStep`.
- **Primary keys must come back from the insert.** The engine links children to copied
  parents through the primary keys that ``bulk_create`` returns. PostgreSQL, SQLite 3.35+
  and MariaDB return them (MariaDB is not tested in CI). MySQL and Oracle do not, so
  auto-increment keys fail there with :py:class:`django.db.NotSupportedError`. Models whose primary key has a
  Python-side default, such as ``UUIDField(default=uuid.uuid4)``, work on any backend.
- **Fields left out of** ``field_copy_actions`` **get their default.** Nothing is copied
  implicitly. ``check_config`` reports these fields as ``copyist.W001``, and required
  fields without a default as ``copyist.E004``.

Model shapes
------------

- **Multi-table inheritance** is not supported, because ``bulk_create`` cannot insert
  into parent and child tables (``copyist.E007``). Abstract base classes and proxy models
  work.
- **Reverse one-to-one relations** cannot be copied with ``MakeCopy`` (``copyist.E002``).
  Copy the related model with its own config in ``compound_copy_actions``.
- **Self-referencing trees** (a model with a foreign key to itself, such as a category
  tree) are not copied level by level yet. ``TAKE_FROM_ORIGIN`` on such a key keeps the
  origin parent (``copyist.W005``). ``UpdateToCopied`` on it fails, because all copies
  of a level are inserted together (``copyist.E011``). Many-to-many links from a model
  to itself work with ``UpdateToCopied``.
- **Primary keys set by hand** (``CharField(primary_key=True)`` without a default) need
  a new value for every copy: use ``TAKE_FROM_INPUT`` or a default (``copyist.E004``,
  ``copyist.E005``).
- **Custom many-to-many** ``through`` **models** get rows with the two link columns only.
  If the ``through`` model has required extra columns (``copyist.E006``), copy it as a
  one-to-many child with ``MakeCopy`` instead.
- **Generic relations** (``GenericForeignKey``) are copied as plain columns
  (``content_type`` and ``object_id``). They are not remapped to copied rows.

Configuration
-------------

- **Each model appears once per config** (``copyist.E009``). Use
  ``compound_copy_actions`` and :py:func:`~django_copyist.UpdateToCopied` for a model
  that has several copied parents.
- **Root configs need a filter** (``copyist.E008``), so that a config never copies a
  whole table by accident.
- **Input values must not be** ``None``. A missing or ``None`` value in ``input_data``
  raises ``ValueError``. ``0``, ``False`` and ``""`` are valid values.

Queries
-------

- The engine reads each tree level with ``IN`` lookups on primary keys. When the backend
  reports a parameter limit, the engine splits long lookups into chunks. For SQLite,
  Django 5.2 reports 999 parameters and Django 6.1 reports the real limit of the
  connection (32 766 by default). PostgreSQL with psycopg has no limit.
- ``compound_copy_actions`` filters, ``IgnoreFilter`` lookups and the ``Q`` object
  passed to ignore functions are not split. On SQLite, a copy fails with "too many SQL
  variables" if one of them holds more than 32 766 primary keys. Use PostgreSQL for
  copies that large.
- The whole copy runs in one transaction on the write database of the first root model,
  or on the ``using`` alias. Ignore functions, filter functions and steps that you write
  run inside it, but they choose their own database unless you pass the alias yourself.
