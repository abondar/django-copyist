Benchmark
=========

The benchmark copies a kanban board tree three ways and compares time and query count:

- **django-copyist** with one :py:class:`~django_copyist.ModelCopyConfig`.
- **django-clone** 5.5.0 (``CloneMixin.make_clone()``), the most used cloning library.
- **naive save() loop**: the hand-written loop most projects start with. It calls
  ``create()`` for every row and ``tags.set()`` for every task.

The tree is ``Board → Column → Task → ChecklistItem``, and every task links to two
tags. Before it reports a time, the script checks that each approach created exactly as
many columns, tasks, checklist items and tag links as the origin has.

Results
-------

Apple M4 Max, Python 3.14.2, Django 5.2.10. PostgreSQL 17 runs in Docker on the same
machine, so every query pays a local network round trip. SQLite 3.50.4 uses a file on
disk. Time is the median of 3 runs for small and medium sizes, one run for large and
xlarge.

"Rows" counts every inserted row: the board, columns, tasks, checklist items and tag
links.

**PostgreSQL 17**

.. list-table::
   :header-rows: 1
   :widths: 10 12 26 16 16 20

   * - Size
     - Rows
     - Approach
     - Seconds
     - Queries
     - copyist faster by
   * - small
     - 79
     - django-copyist
     - 0.009
     - 14
     -
   * -
     -
     - django-clone
     - 0.037
     - 211
     - 4×
   * -
     -
     - naive save() loop
     - 0.025
     - 113
     - 3×
   * - medium
     - 1 611
     - django-copyist
     - 0.035
     - 14
     -
   * -
     -
     - django-clone
     - 0.674
     - 4 444
     - 19×
   * -
     -
     - naive save() loop
     - 0.464
     - 2 022
     - 13×
   * - large
     - 16 021
     - django-copyist
     - 0.363
     - 14
     -
   * -
     -
     - django-clone
     - 7.714
     - 44 084
     - 21×
   * -
     -
     - naive save() loop
     - 4.662
     - 20 042
     - 13×
   * - xlarge
     - 160 041
     - django-copyist
     - 3.484
     - 14
     -
   * -
     -
     - django-clone
     - 82.595
     - 400 164
     - 24×
   * -
     -
     - naive save() loop
     - 61.544
     - 240 082
     - 18×

**SQLite 3.50.4**

.. list-table::
   :header-rows: 1
   :widths: 10 12 26 16 16 20

   * - Size
     - Rows
     - Approach
     - Seconds
     - Queries
     - copyist faster by
   * - small
     - 79
     - django-copyist
     - 0.003
     - 15
     -
   * -
     -
     - django-clone
     - 0.010
     - 212
     - 3×
   * -
     -
     - naive save() loop
     - 0.008
     - 114
     - 3×
   * - medium
     - 1 611
     - django-copyist
     - 0.020
     - 18
     -
   * -
     -
     - django-clone
     - 0.161
     - 4 445
     - 8×
   * -
     -
     - naive save() loop
     - 0.122
     - 2 023
     - 6×
   * - large
     - 16 021
     - django-copyist
     - 0.179
     - 67
     -
   * -
     -
     - django-clone
     - 1.511
     - 44 085
     - 8×
   * -
     -
     - naive save() loop
     - 1.195
     - 20 043
     - 7×
   * - xlarge
     - 160 041
     - django-copyist
     - 1.839
     - 587
     -
   * -
     -
     - django-clone
     - 20.328
     - 400 165
     - 11×
   * -
     -
     - naive save() loop
     - 17.405
     - 240 083
     - 9×

What the numbers show
---------------------

- On PostgreSQL, django-copyist runs the same 14 queries for 79 rows and for 160 041
  rows. The other approaches run 2 to 3 queries per row.
- On SQLite, the query count of django-copyist grows slowly. Django 5.2 reports a limit
  of 999 parameters per SQLite query, so the engine splits long ``IN`` lookups into
  chunks. The xlarge size has 40 000 tasks, more than the 32 766 variables that SQLite
  itself allows in one statement.
- The gap is largest where each query costs a network round trip. A remote database
  widens it further.
- What you give up for the speed: copies do not call ``save()`` or send model signals.
  See :doc:`limitations`.

Sizes
-----

======  =======  ================  ==================  =========
Size    Columns  Tasks per column  Items per task      Tasks
======  =======  ================  ==================  =========
small   3        5                 2                   15
medium  10       20                5                   200
large   20       100               5                   2 000
xlarge  40       1 000             1                   40 000
======  =======  ================  ==================  =========

Run it yourself
---------------

The benchmark lives in the ``benchmarks/`` directory of the repository.

.. code-block:: console

    uv run --extra dev --extra bench python -m benchmarks.run

    # PostgreSQL
    docker run -d --rm -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:17
    POSTGRES_HOST=localhost uv run --extra dev --extra bench python -m benchmarks.run

Options: ``--sizes small,medium``, ``--approaches django-copyist,django-clone``,
``--repeat 5``, and ``--max-seconds`` to skip larger sizes for an approach that gets
too slow.
