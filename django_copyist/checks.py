"""
Static checks for copy configurations.

:func:`check_config` compares a configuration with the Django model metadata and
reports problems before any query runs. Run it in a unit test for every
configuration you ship::

    from django_copyist import check_config

    def test_company_copy_config_is_valid():
        check_config(COMPANY_COPY_CONFIG, raise_on_error=True)
"""

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import models
from django.db.models import GeneratedField, Model
from django.db.models.fields.related_descriptors import (
    ForwardManyToOneDescriptor,
    ManyToManyDescriptor,
    ReverseManyToOneDescriptor,
    ReverseOneToOneDescriptor,
)
from django.db.models.query_utils import DeferredAttribute

from django_copyist.config import (
    CopyActions,
    FieldCopyConfig,
    MapKeys,
    ModelCopyConfig,
    find_map_key_conflicts,
)

if TYPE_CHECKING:
    from django_copyist.copyist import CopyistConfig


class ConfigIssueLevel(StrEnum):
    #: The copy fails or writes wrong data.
    ERROR = "ERROR"
    #: The copy runs, but probably not the way you expect.
    WARNING = "WARNING"


@dataclass(frozen=True)
class ConfigIssue:
    """
    One problem that :func:`check_config` found.

    :ivar level: ``ERROR`` or ``WARNING``.
    :ivar code: Stable identifier, for example ``copyist.E004``. Use it to filter issues.
    :ivar model: Label of the model whose config has the problem, for example ``demo.Task``.
    :ivar field: Field name, or None if the issue is about the whole model config.
    :ivar message: What is wrong and how to fix it.
    """

    level: ConfigIssueLevel
    code: str
    model: str
    field: str | None
    message: str

    def __str__(self) -> str:
        location = f"{self.model}.{self.field}" if self.field else self.model
        return f"{self.code} {self.level} {location}: {self.message}"


def _relation_kind(model: type[Model], name: str) -> str | None:
    """
    Classify ``name`` on ``model`` the same way the copy engine does.

    Returns one of ``m2m``, ``fk``, ``reverse_fk``, ``reverse_o2o``, ``concrete``, or None.
    """
    descriptor = getattr(model, name, None)
    if isinstance(descriptor, ManyToManyDescriptor):
        return "m2m"
    if isinstance(descriptor, ForwardManyToOneDescriptor):
        return "fk"
    if isinstance(descriptor, ReverseManyToOneDescriptor):
        return "reverse_fk"
    if isinstance(descriptor, ReverseOneToOneDescriptor):
        return "reverse_o2o"
    if isinstance(descriptor, DeferredAttribute):
        return "concrete"
    return None


def _concrete_field(model: type[Model], name: str) -> "models.Field[Any, Any] | None":
    """Concrete field for a name or attname (``project`` or ``project_id``)."""
    try:
        field = model._meta.get_field(name)
    except FieldDoesNotExist:
        return None
    if isinstance(field, models.Field) and field.concrete:
        return field
    return None


def _related_model(model: type[Model], name: str) -> type[Model]:
    """Model on the other side of relation ``name``. ``name`` must be a relation."""
    descriptor = getattr(model, name)
    if isinstance(descriptor, ManyToManyDescriptor):
        related = descriptor.field.model if descriptor.reverse else descriptor.field.related_model
    elif isinstance(descriptor, ReverseManyToOneDescriptor):
        # The FK lives on the child model.
        related = descriptor.field.model
    else:
        related = descriptor.field.related_model
    return related


def _is_filled_by_database_or_django(field: "models.Field[Any, Any]") -> bool:
    if field.primary_key:
        # Auto-increment keys, keys with a default (uuid4) and MTI parent links get a
        # value without the config. A key set by hand does not. isinstance() with
        # AutoField also matches BigAutoField and SmallAutoField.
        parent_link = bool(field.remote_field is not None and field.remote_field.parent_link)
        return isinstance(field, models.AutoField) or _has_default(field) or parent_link
    if isinstance(field, GeneratedField):
        return True
    if getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False):
        return True
    return False


def _has_default(field: "models.Field[Any, Any]") -> bool:
    if field.has_default():
        return True
    db_default = getattr(field, "db_default", models.NOT_PROVIDED)
    return db_default is not models.NOT_PROVIDED


class _Checker:
    def __init__(self, root_configs: list[ModelCopyConfig], map_keys: MapKeys):
        self.root_configs = root_configs
        self.map_keys = map_keys
        self.issues: list[ConfigIssue] = []
        self.copied_models: Counter[str] = Counter()

    def add(
        self,
        level: ConfigIssueLevel,
        code: str,
        model: type[Model],
        field: str | None,
        message: str,
    ) -> None:
        self.issues.append(
            ConfigIssue(
                level=level, code=code, model=model._meta.label, field=field, message=message
            )
        )

    def error(self, code: str, model: type[Model], field: str | None, message: str) -> None:
        self.add(ConfigIssueLevel.ERROR, code, model, field, message)

    def warning(self, code: str, model: type[Model], field: str | None, message: str) -> None:
        self.add(ConfigIssueLevel.WARNING, code, model, field, message)

    def collect(self, config: ModelCopyConfig) -> None:
        self.copied_models[config.model._meta.label] += 1
        for field_config in config.field_copy_actions.values():
            if field_config.action == CopyActions.MAKE_COPY and field_config.copy_with_config:
                self.collect(field_config.copy_with_config)
        for compound in config.compound_copy_actions:
            self.collect(compound)

    def run(self) -> list[ConfigIssue]:
        if self.map_keys == MapKeys.MODEL_NAME:
            for name, labels in find_map_key_conflicts(self.root_configs).items():
                self.issues.append(
                    ConfigIssue(
                        level=ConfigIssueLevel.ERROR,
                        code="copyist.E012",
                        model=", ".join(labels),
                        field=None,
                        message=(
                            f"Models {', '.join(labels)} share the class name '{name}', so "
                            f"maps keyed by class name would mix them. Use "
                            f"CopyistConfig(..., map_keys=MapKeys.LABEL)."
                        ),
                    )
                )
        for root in self.root_configs:
            self.collect(root)
        for root in self.root_configs:
            self.check_model(root, parent_fk=None, is_root=True)
        return self.issues

    def check_model(
        self,
        config: ModelCopyConfig,
        parent_fk: "models.ForeignKey[Any, Any] | None",
        is_root: bool,
    ) -> None:
        model = config.model
        label = model._meta.label

        if self.copied_models[label] > 1:
            self.error(
                "copyist.E009",
                model,
                None,
                f"{label} is configured for copy {self.copied_models[label]} times. "
                f"Configure each model once; reference other copies with UpdateToCopied.",
            )
            # Report once per model.
            self.copied_models[label] = 1

        if is_root and not config.filter_field_to_input_key:
            self.error(
                "copyist.E008",
                model,
                None,
                "A root config needs filter_field_to_input_key, for example "
                '{"id": "company_id"}, so that it does not copy the whole table.',
            )

        if model._meta.parents:
            self.error(
                "copyist.E007",
                model,
                None,
                "Multi-table inheritance is not supported: bulk_create() cannot insert "
                "into parent and child tables.",
            )

        covered: set[str] = set()
        if parent_fk is not None:
            covered.add(parent_fk.name)

        for name, field_config in config.field_copy_actions.items():
            self.check_field(config, name, field_config, covered)

        self.check_uncovered_fields(config, covered)
        self.check_unique_sets(config)

        for name, field_config in config.field_copy_actions.items():
            if (
                field_config.action == CopyActions.MAKE_COPY
                and _relation_kind(model, name) == "reverse_fk"
            ):
                assert field_config.copy_with_config is not None  # set by __post_init__
                self.check_model(
                    field_config.copy_with_config,
                    parent_fk=getattr(model, name).field,
                    is_root=False,
                )
        for compound in config.compound_copy_actions:
            self.check_model(compound, parent_fk=None, is_root=False)

    def check_field(
        self,
        config: ModelCopyConfig,
        name: str,
        field_config: FieldCopyConfig,
        covered: set[str],
    ) -> None:
        model = config.model
        kind = _relation_kind(model, name)
        action = field_config.action

        if kind is None:
            self.error(
                "copyist.E001",
                model,
                name,
                f"{model._meta.label} has no field or relation named '{name}'.",
            )
            return

        concrete = _concrete_field(model, name)
        if concrete is not None:
            covered.add(concrete.name)

        allowed = {
            CopyActions.TAKE_FROM_ORIGIN: {"concrete", "fk", "m2m"},
            CopyActions.TAKE_FROM_INPUT: {"concrete", "fk"},
            CopyActions.MAKE_COPY: {"reverse_fk"},
            CopyActions.UPDATE_TO_COPIED: {"fk", "m2m"},
            CopyActions.SET_TO_FILTER: {"fk", "m2m"},
        }[action]
        if kind not in allowed:
            hint = ""
            if kind == "reverse_o2o":
                hint = " Reverse one-to-one relations cannot be copied with MAKE_COPY yet."
            elif kind == "reverse_fk":
                hint = " Use MakeCopy(...) to copy related rows."
            self.error(
                "copyist.E002",
                model,
                name,
                f"{action} cannot be used on a {kind.replace('_', ' ')} field. "
                f"Allowed field kinds: {', '.join(sorted(allowed))}.{hint}",
            )
            return

        if action in (CopyActions.UPDATE_TO_COPIED, CopyActions.SET_TO_FILTER):
            related = _related_model(model, name)
            reference_to = field_config.reference_to
            assert reference_to is not None  # set by __post_init__
            if reference_to is not related:
                self.error(
                    "copyist.E003",
                    model,
                    name,
                    f"reference_to is {reference_to._meta.label}, but "
                    f"'{name}' points to {related._meta.label}.",
                )
        if (
            action == CopyActions.UPDATE_TO_COPIED
            and kind == "fk"
            and field_config.reference_to is model
        ):
            self.error(
                "copyist.E011",
                model,
                name,
                f"UpdateToCopied({model._meta.label}) on '{name}' points the model at itself. "
                f"Copying self-referencing trees is not supported yet: the copies of a "
                f"level are inserted together, so the parent copy does not exist yet. "
                f"Keep TAKE_FROM_ORIGIN or set the parent in a postcopy step.",
            )
        elif action == CopyActions.UPDATE_TO_COPIED and field_config.reference_to:
            if field_config.reference_to._meta.label not in self.copied_models:
                self.error(
                    "copyist.E010",
                    model,
                    name,
                    f"UpdateToCopied({field_config.reference_to._meta.label}) needs that model "
                    f"to be copied by the same config, but no config copies it.",
                )
        if action == CopyActions.MAKE_COPY:
            related = _related_model(model, name)
            assert field_config.copy_with_config is not None  # set by __post_init__
            nested_model = field_config.copy_with_config.model
            if nested_model is not related:
                self.error(
                    "copyist.E003",
                    model,
                    name,
                    f"MakeCopy config is for {nested_model._meta.label}, but '{name}' "
                    f"holds {related._meta.label} rows.",
                )
        if action == CopyActions.TAKE_FROM_ORIGIN and concrete is not None and concrete.unique:
            self.error(
                "copyist.E005",
                model,
                name,
                f"'{name}' is unique, so copying its value from the origin violates the "
                f"constraint. Use TAKE_FROM_INPUT or set it in a postcopy step.",
            )
        if (
            action == CopyActions.TAKE_FROM_ORIGIN
            and kind == "fk"
            and _related_model(model, name) is model
        ):
            self.warning(
                "copyist.W005",
                model,
                name,
                f"'{name}' points to {model._meta.label} itself. Copies keep the origin "
                f"parent: copying self-referencing trees is not supported yet.",
            )
        if kind == "m2m":
            self.check_through_model(model, name)

    def check_through_model(self, model: type[Model], name: str) -> None:
        descriptor = getattr(model, name)
        through = descriptor.through
        if through._meta.auto_created:
            return
        m2m_field = descriptor.field
        link_names = {m2m_field.m2m_field_name(), m2m_field.m2m_reverse_field_name()}
        for field in through._meta.concrete_fields:
            if field.name in link_names or _is_filled_by_database_or_django(field):
                continue
            if field.null or _has_default(field):
                self.warning(
                    "copyist.W004",
                    model,
                    name,
                    f"Through model {through._meta.label} has extra column '{field.name}'. "
                    f"Copied relations get its default value, not the origin value.",
                )
            else:
                self.error(
                    "copyist.E006",
                    model,
                    name,
                    f"Through model {through._meta.label} has required column "
                    f"'{field.name}' without a default. django-copyist creates through "
                    f"rows with the two link columns only. Copy the through model with "
                    f"its own ModelCopyConfig in compound_copy_actions instead.",
                )

    def check_uncovered_fields(self, config: ModelCopyConfig, covered: set[str]) -> None:
        model = config.model
        for field in model._meta.concrete_fields:
            if field.name in covered or _is_filled_by_database_or_django(field):
                continue
            if model._meta.parents and field.remote_field and field.remote_field.parent_link:
                continue
            if field.primary_key:
                self.error(
                    "copyist.E004",
                    model,
                    field.name,
                    f"Primary key '{field.name}' has no default, so every copy needs a new "
                    f"value. Add it with TAKE_FROM_INPUT, or give the field a default.",
                )
            elif _has_default(field) or field.null:
                default = "NULL" if not _has_default(field) else "its default"
                self.warning(
                    "copyist.W001",
                    model,
                    field.name,
                    f"'{field.name}' is not in field_copy_actions, so copies get {default}. "
                    f"Add TAKE_FROM_ORIGIN to keep the origin value.",
                )
            elif field.empty_strings_allowed and not field.is_relation:
                self.warning(
                    "copyist.W001",
                    model,
                    field.name,
                    f"'{field.name}' is not in field_copy_actions, so copies get an empty "
                    f"string. Add TAKE_FROM_ORIGIN to keep the origin value.",
                )
            else:
                self.error(
                    "copyist.E004",
                    model,
                    field.name,
                    f"'{field.name}' is required and has no default, but it is not in "
                    f"field_copy_actions. The insert fails with IntegrityError.",
                )

        for field in model._meta.many_to_many:
            through = cast("type[Model]", field.remote_field.through)
            if not through._meta.auto_created:
                # Rows of a custom through model are copied like any other model.
                continue
            if field.name not in config.field_copy_actions:
                self.warning(
                    "copyist.W003",
                    model,
                    field.name,
                    f"Many-to-many '{field.name}' is not in field_copy_actions, so copies "
                    f"have no {field.name} relations.",
                )

    def check_unique_sets(self, config: ModelCopyConfig) -> None:
        model = config.model
        unique_sets: list[tuple[str, ...]] = [tuple(u) for u in model._meta.unique_together]
        for constraint in model._meta.total_unique_constraints:
            unique_sets.append(tuple(constraint.fields))

        for fields in unique_sets:
            if len(fields) < 2:
                continue
            actions = []
            for name in fields:
                field = _concrete_field(model, name)
                action = None
                for key in (name, field.attname if field else None):
                    if key in config.field_copy_actions:
                        action = config.field_copy_actions[key].action
                actions.append(action)
            if all(a == CopyActions.TAKE_FROM_ORIGIN for a in actions):
                self.warning(
                    "copyist.W002",
                    model,
                    None,
                    f"All fields of unique set {fields} are copied from the origin, so the "
                    f"copy will likely violate the constraint.",
                )


def check_config(
    config: "ModelCopyConfig | CopyistConfig",
    *,
    raise_on_error: bool = False,
) -> list[ConfigIssue]:
    """
    Check a copy configuration against the Django model metadata.

    The check runs no queries. It finds problems that would otherwise surface in the
    middle of a copy, or not at all:

    * ``copyist.E001``: unknown field name.
    * ``copyist.E002``: action does not fit the field kind (for example ``MAKE_COPY``
      on a forward foreign key).
    * ``copyist.E003``: ``reference_to`` or a ``MakeCopy`` model does not match the relation.
    * ``copyist.E004``: required field without default is not copied.
    * ``copyist.E005``: unique field is copied from the origin.
    * ``copyist.E006``: custom many-to-many ``through`` model has required extra columns.
    * ``copyist.E007``: multi-table inheritance.
    * ``copyist.E008``: root config without ``filter_field_to_input_key``.
    * ``copyist.E009``: model configured more than once.
    * ``copyist.E010``: ``UpdateToCopied`` references a model that the config never copies.
    * ``copyist.E011``: ``UpdateToCopied`` on a foreign key to the same model (a tree).
      Many-to-many links to the same model work.
    * ``copyist.E012``: two models share a class name while maps are keyed by class
      name. Use ``CopyistConfig(..., map_keys=MapKeys.LABEL)``.
    * ``copyist.W001``: field is not copied and gets its default.
    * ``copyist.W002``: all fields of a unique set are copied from the origin.
    * ``copyist.W003``: many-to-many field is not copied.
    * ``copyist.W004``: custom ``through`` model has extra columns that get defaults.
    * ``copyist.W005``: a foreign key to the same model is copied from the origin.

    :param config: A :class:`~django_copyist.config.ModelCopyConfig` or a
        :class:`~django_copyist.copyist.CopyistConfig`.
    :param raise_on_error: Raise :class:`django.core.exceptions.ImproperlyConfigured`
        if any issue has level ``ERROR``.
    :return: All issues, errors first.
    """
    if isinstance(config, ModelCopyConfig):
        roots = [config]
        map_keys = MapKeys.MODEL_NAME
    else:
        roots = list(config.model_configs)
        map_keys = config.map_keys

    issues = _Checker(roots, map_keys).run()
    issues.sort(key=lambda i: (i.level != ConfigIssueLevel.ERROR, i.code, i.model))

    if raise_on_error:
        errors = [i for i in issues if i.level == ConfigIssueLevel.ERROR]
        if errors:
            raise ImproperlyConfigured(
                "django-copyist config has errors:\n" + "\n".join(f"  {e}" for e in errors)
            )
    return issues
