"""
Generate a starting copy configuration from Django model metadata.

The generated code copies every plain field from the origin and copies one-to-many
children with ``MakeCopy`` down to the requested depth. Decisions the generator
cannot make on its own are marked with ``TODO`` comments.
"""

import keyword
import re
import textwrap
from dataclasses import dataclass, field
from typing import Any, cast

from django.db import models
from django.db.models import ForeignObjectRel, Model

from django_copyist.checks import _has_default, _is_filled_by_database_or_django

INDENT = "    "


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _comment(indent: str, text: str) -> list[str]:
    return textwrap.wrap(
        text,
        width=88,
        initial_indent=f"{indent}# ",
        subsequent_indent=f"{indent}#   ",
        break_on_hyphens=False,
        break_long_words=False,
    )


def _literal(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class _Generator:
    depth: int
    used_names: set[str] = field(default_factory=set)
    models_used: dict[str, set[str]] = field(default_factory=dict)
    tree: set[type[Model]] = field(default_factory=set)

    def use(self, name: str) -> str:
        self.used_names.add(name)
        return name

    def model_ref(self, model: type[Model]) -> str:
        self.models_used.setdefault(model.__module__, set()).add(model.__name__)
        return model.__name__

    def collect_tree(self, model: type[Model], depth: int) -> None:
        self.tree.add(model)
        if depth <= 0:
            return
        for rel in self._children(model):
            if rel.related_model not in self.tree:
                self.collect_tree(rel.related_model, depth - 1)

    @staticmethod
    def _children(model: type[Model]) -> list[ForeignObjectRel]:
        return [
            rel
            for rel in model._meta.related_objects
            if rel.one_to_many and not rel.related_model._meta.auto_created
        ]

    def render_model(
        self,
        model: type[Model],
        level: int,
        depth: int,
        parent_fk: "models.Field[Any, Any] | None",
        visited: set[type[Model]],
        root_input_key: str | None,
    ) -> list[str]:
        pad = INDENT * level
        lines = [f"{pad}{self.use('ModelCopyConfig')}("]
        lines.append(f"{pad}{INDENT}model={self.model_ref(model)},")
        if model._meta.parents:
            lines.append(
                f"{pad}{INDENT}# TODO: multi-table inheritance is not supported "
                f"(check_config reports copyist.E007)."
            )
        if root_input_key:
            lines.append(
                f"{pad}{INDENT}filter_field_to_input_key={{{_literal('pk')}: "
                f"{_literal(root_input_key)}}},"
            )
        lines.append(f"{pad}{INDENT}field_copy_actions={{")
        body = INDENT * (level + 2)
        model_key = _snake(model.__name__)

        for f in model._meta.concrete_fields:
            if _is_filled_by_database_or_django(f):
                continue
            if parent_fk is not None and f.name == parent_fk.name:
                continue
            if f.remote_field is not None and getattr(f.remote_field, "parent_link", False):
                continue
            key = _literal(f.name)
            if f.unique:
                input_key = f"{model_key}_{f.name}"
                lines.extend(
                    _comment(
                        body,
                        f"TODO: '{f.name}' is unique. Pass a new value in input_data, "
                        f"or set it in a postcopy step if several rows are copied.",
                    )
                )
                lines.append(f"{body}{key}: {self.use('TakeFromInput')}({_literal(input_key)}),")
                continue
            target = f.related_model
            if f.is_relation and target is model:
                lines.extend(
                    _comment(
                        body,
                        f"TODO: '{f.name}' points to {model.__name__} itself. Copies keep the "
                        f"origin parent: copying self-referencing trees is not supported yet.",
                    )
                )
            elif f.is_relation and target in self.tree:
                lines.extend(
                    _comment(
                        body,
                        f"TODO: {target.__name__} is also copied. This keeps the "
                        f"origin reference. To point at the copy, move this model to "
                        f"compound_copy_actions and use UpdateToCopied({target.__name__}).",
                    )
                )
            lines.append(f"{body}{key}: {self.use('TAKE_FROM_ORIGIN')},")

        for m2m in model._meta.many_to_many:
            key = _literal(m2m.name)
            through = cast("type[Model]", m2m.remote_field.through)
            if not through._meta.auto_created:
                link_names = {m2m.m2m_field_name(), m2m.m2m_reverse_field_name()}
                required = [
                    tf.name
                    for tf in through._meta.concrete_fields
                    if tf.name not in link_names
                    and not _is_filled_by_database_or_django(tf)
                    and not tf.null
                    and not _has_default(tf)
                ]
                if required:
                    lines.extend(
                        _comment(
                            body,
                            f"TODO: {m2m.name} uses through model {through.__name__} with "
                            f"required columns {required}. Copy {through.__name__} rows with "
                            f"MakeCopy or compound_copy_actions instead.",
                        )
                    )
                    lines.append(f"{body}# {key}: TAKE_FROM_ORIGIN,")
                    continue
            if m2m.related_model in self.tree:
                lines.extend(
                    _comment(
                        body,
                        f"TODO: {m2m.related_model.__name__} is also copied. This links "
                        f"copies to the origin rows. Use UpdateToCopied to link to the copies.",
                    )
                )
            lines.append(f"{body}{key}: {self.use('TAKE_FROM_ORIGIN')},")

        for rel in self._children(model):
            accessor = rel.get_accessor_name()
            if accessor is None:
                # Hidden relation (related_name ending with "+"): no accessor to copy by.
                continue
            child = rel.related_model
            key = _literal(accessor)
            if depth <= 0:
                lines.extend(
                    _comment(
                        body,
                        f"{key}: {child.__name__} rows are not copied "
                        f"(raise --depth to include them).",
                    )
                )
                continue
            if child in visited:
                lines.extend(
                    _comment(
                        body,
                        f"{key}: {child.__name__} is already copied elsewhere in this "
                        f"config. Use compound_copy_actions if it needs several parents.",
                    )
                )
                continue
            if child._meta.parents:
                lines.extend(
                    _comment(
                        body,
                        f"{key}: {child.__name__} uses multi-table inheritance, "
                        f"which is not supported.",
                    )
                )
                continue
            visited.add(child)
            lines.append(f"{body}{key}: {self.use('MakeCopy')}(")
            lines.extend(
                self.render_model(
                    child,
                    level=level + 3,
                    depth=depth - 1,
                    parent_fk=rel.field,
                    visited=visited,
                    root_input_key=None,
                )
            )
            lines.append(f"{body}),")

        for rel in model._meta.related_objects:
            if rel.one_to_one:
                lines.extend(
                    _comment(
                        body,
                        f"{_literal(rel.get_accessor_name() or rel.name)}: reverse one-to-one "
                        f"{rel.related_model.__name__} is not copied (not supported by MakeCopy).",
                    )
                )

        lines.append(f"{pad}{INDENT}}},")
        lines.append(f"{pad})")
        return lines


def scaffold_config(
    model: type[Model],
    *,
    depth: int = 1,
    name: str | None = None,
    input_key: str | None = None,
) -> str:
    """
    Return Python source for a :class:`~django_copyist.config.ModelCopyConfig` of ``model``.

    The result is a starting point. It copies:

    * every concrete field, except the primary key, auto-filled fields and generated
      fields, with ``TAKE_FROM_ORIGIN``;
    * unique fields with ``TakeFromInput``, because the origin value would violate the
      constraint;
    * forward many-to-many fields with ``TAKE_FROM_ORIGIN``;
    * one-to-many children with ``MakeCopy``, down to ``depth`` levels.

    Read the ``TODO`` comments, then run :func:`~django_copyist.check_config` on the
    result.

    :param model: Root model class.
    :param depth: How many levels of one-to-many children to copy. 0 copies the root only.
    :param name: Name of the generated constant. Defaults to ``<MODEL>_COPY_CONFIG``.
    :param input_key: ``input_data`` key that selects the root row. Defaults to
        ``<model>_pk``.
    :return: Source code of a Python module.
    """
    if depth < 0:
        raise ValueError("depth must be 0 or greater")

    model_key = _snake(model.__name__)
    name = name or f"{model_key.upper()}_COPY_CONFIG"
    if not name.isidentifier() or keyword.iskeyword(name):
        raise ValueError(f"{name!r} is not a valid Python identifier")
    input_key = input_key or f"{model_key}_pk"

    generator = _Generator(depth=depth)
    generator.collect_tree(model, depth)
    body = generator.render_model(
        model,
        level=0,
        depth=depth,
        parent_fk=None,
        visited={model},
        root_input_key=input_key,
    )
    body[0] = f"{name} = {body[0]}"

    lines = [
        '"""',
        f"Copy config for {model._meta.label}.",
        "",
        "Generated by `manage.py copyist_scaffold`. Review every TODO, then run",
        "django_copyist.check_config() on it in a test.",
        "",
        "Usage:",
        "",
        f"    result = run_copy({name}, input_data={{{_literal(input_key)}: origin.pk}})",
        '"""',
        "",
        "from django_copyist import " + ", ".join(sorted(generator.used_names)),
    ]
    for module in sorted(generator.models_used):
        names = ", ".join(sorted(generator.models_used[module]))
        lines.append(f"from {module} import {names}")
    lines.append("")
    lines.append("")
    lines.extend(body)
    return "\n".join(lines) + "\n"
