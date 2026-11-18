"""
Copy a kanban board tree with django-copyist, django-clone and a naive loop.

Usage::

    uv run --extra dev --extra bench python -m benchmarks.run
    POSTGRES_HOST=localhost uv run --extra dev --extra bench python -m benchmarks.run

Every approach copies the same tree, and the script checks that each copy has the
same number of rows as the origin before it reports a time.
"""

import argparse
import os
import platform
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "benchmarks.settings")
django.setup()

from django.db import connection, transaction  # noqa: E402

from benchmarks.models import Board, ChecklistItem, Column, Tag, Task  # noqa: E402
from django_copyist import TAKE_FROM_ORIGIN, MakeCopy, ModelCopyConfig, run_copy  # noqa: E402

BOARD_COPY_CONFIG = ModelCopyConfig(
    model=Board,
    filter_field_to_input_key={"id": "board_id"},
    field_copy_actions={
        "name": TAKE_FROM_ORIGIN,
        "columns": MakeCopy(
            ModelCopyConfig(
                model=Column,
                field_copy_actions={
                    "name": TAKE_FROM_ORIGIN,
                    "position": TAKE_FROM_ORIGIN,
                    "tasks": MakeCopy(
                        ModelCopyConfig(
                            model=Task,
                            field_copy_actions={
                                "title": TAKE_FROM_ORIGIN,
                                "description": TAKE_FROM_ORIGIN,
                                "priority": TAKE_FROM_ORIGIN,
                                "tags": TAKE_FROM_ORIGIN,
                                "checklist_items": MakeCopy(
                                    ModelCopyConfig(
                                        model=ChecklistItem,
                                        field_copy_actions={
                                            "text": TAKE_FROM_ORIGIN,
                                            "done": TAKE_FROM_ORIGIN,
                                        },
                                    )
                                ),
                            },
                        )
                    ),
                },
            )
        ),
    },
)


def copy_with_copyist(board: Board) -> int:
    result = run_copy(BOARD_COPY_CONFIG, input_data={"board_id": board.pk})
    assert result.is_copy_successful
    return int(result.copies_of(Board)[str(board.pk)])


def copy_with_django_clone(board: Board) -> int:
    with transaction.atomic():
        return board.make_clone().pk


def copy_naively(board: Board) -> int:
    """The loop most projects start with: save() every row, one by one."""
    with transaction.atomic():
        new_board = Board.objects.create(name=board.name)
        for column in board.columns.all():
            new_column = Column.objects.create(
                board=new_board, name=column.name, position=column.position
            )
            for task in column.tasks.all():
                new_task = Task.objects.create(
                    column=new_column,
                    title=task.title,
                    description=task.description,
                    priority=task.priority,
                )
                new_task.tags.set(task.tags.all())
                for item in task.checklist_items.all():
                    ChecklistItem.objects.create(task=new_task, text=item.text, done=item.done)
        return new_board.pk


APPROACHES: dict[str, Callable[[Board], int]] = {
    "django-copyist": copy_with_copyist,
    "django-clone": copy_with_django_clone,
    "naive save() loop": copy_naively,
}


@dataclass(frozen=True)
class Size:
    name: str
    columns: int
    tasks_per_column: int
    items_per_task: int
    tags_per_task: int = 2

    @property
    def tasks(self) -> int:
        return self.columns * self.tasks_per_column

    @property
    def rows(self) -> int:
        items = self.tasks * self.items_per_task
        links = self.tasks * self.tags_per_task
        return 1 + self.columns + self.tasks + items + links


SIZES = {
    s.name: s
    for s in [
        Size("small", columns=3, tasks_per_column=5, items_per_task=2),
        Size("medium", columns=10, tasks_per_column=20, items_per_task=5),
        Size("large", columns=20, tasks_per_column=100, items_per_task=5),
        # More tasks than SQLite's default limit of 32766 bound variables per query.
        Size("xlarge", columns=40, tasks_per_column=1000, items_per_task=1),
    ]
}


def clear() -> None:
    for model in (Task.tags.through, ChecklistItem, Task, Column, Board, Tag):
        model.objects.all()._raw_delete(connection.alias)


def seed(size: Size) -> Board:
    tags = Tag.objects.bulk_create([Tag(name=f"tag {i}") for i in range(10)])
    board = Board.objects.create(name="Origin board")
    columns = Column.objects.bulk_create(
        [Column(board=board, name=f"Column {c}", position=c) for c in range(size.columns)]
    )
    tasks = Task.objects.bulk_create(
        [
            Task(
                column=column,
                title=f"Task {c}.{t}",
                description="Lorem ipsum dolor sit amet. " * 4,
                priority=t % 5,
            )
            for c, column in enumerate(columns)
            for t in range(size.tasks_per_column)
        ],
        batch_size=2000,
    )
    ChecklistItem.objects.bulk_create(
        [
            ChecklistItem(task=task, text=f"Item {i}", done=bool(i % 2))
            for task in tasks
            for i in range(size.items_per_task)
        ],
        batch_size=2000,
    )
    Task.tags.through.objects.bulk_create(
        [
            Task.tags.through(task_id=task.pk, tag_id=tags[(n + k) % len(tags)].pk)
            for n, task in enumerate(tasks)
            for k in range(size.tags_per_task)
        ],
        batch_size=2000,
    )
    return board


def tree_counts(board_id: int) -> tuple[int, int, int, int]:
    return (
        Column.objects.filter(board_id=board_id).count(),
        Task.objects.filter(column__board_id=board_id).count(),
        ChecklistItem.objects.filter(task__column__board_id=board_id).count(),
        Task.tags.through.objects.filter(task__column__board_id=board_id).count(),
    )


@dataclass
class Measurement:
    seconds: float
    queries: int


def measure(approach: Callable[[Board], int], size: Size) -> Measurement:
    clear()
    board = seed(size)
    expected = tree_counts(board.pk)

    queries = 0

    def count(execute, sql, params, many, context):
        nonlocal queries
        queries += 1
        return execute(sql, params, many, context)

    with connection.execute_wrapper(count):
        start = time.perf_counter()
        new_board_id = approach(board)
        seconds = time.perf_counter() - start

    copied = tree_counts(new_board_id)
    if copied != expected:
        raise AssertionError(f"copy has {copied} rows, origin has {expected}")
    return Measurement(seconds=seconds, queries=queries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sizes", default="small,medium,large,xlarge")
    parser.add_argument("--approaches", default=",".join(APPROACHES))
    parser.add_argument("--repeat", type=int, default=3, help="Runs per cell; median is kept.")
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=120,
        help="Skip larger sizes for an approach once one run takes longer than this.",
    )
    args = parser.parse_args()

    test_db = connection.creation.create_test_db(verbosity=0, autoclobber=True)
    try:
        if connection.vendor == "sqlite":
            db_version = ".".join(map(str, connection.Database.sqlite_version_info))
        else:
            db_version = str(connection.pg_version)
        vendor = f"{connection.vendor} {db_version}"
        print(
            f"# Python {platform.python_version()}, Django {django.get_version()}, "
            f"{vendor}, {platform.machine()} {platform.system()}"
        )
        print(f"# database: {test_db}")
        print()
        header = (
            f"| {'size':<8} | {'rows':>7} | {'approach':<18} | {'seconds':>9} | {'queries':>8} |"
        )
        print(header)
        print("|" + "|".join("-" * (len(c) + 0) for c in header.split("|")[1:-1]) + "|")

        too_slow: set[str] = set()
        for size_name in args.sizes.split(","):
            size = SIZES[size_name]
            for approach_name in args.approaches.split(","):
                if approach_name in too_slow:
                    print(
                        f"| {size.name:<8} | {size.rows:>7} | {approach_name:<18} "
                        f"| {'skipped':>9} | {'':>8} |"
                    )
                    continue
                runs = [
                    measure(APPROACHES[approach_name], size)
                    for _ in range(1 if size.name in ("large", "xlarge") else args.repeat)
                ]
                seconds = statistics.median(r.seconds for r in runs)
                queries = runs[0].queries
                print(
                    f"| {size.name:<8} | {size.rows:>7} | {approach_name:<18} "
                    f"| {seconds:>9.3f} | {queries:>8} |",
                    flush=True,
                )
                if seconds > args.max_seconds:
                    too_slow.add(approach_name)
    finally:
        clear()
        connection.creation.destroy_test_db(test_db, verbosity=0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
