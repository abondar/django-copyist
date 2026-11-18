from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, NotSupportedError, connections, router, transaction
from django.db.models import ForeignKey, Manager, Model, Q, QuerySet
from django.db.models.fields.related_descriptors import (
    ForwardManyToOneDescriptor,
    ManyToManyDescriptor,
    ReverseManyToOneDescriptor,
)

from django_copyist.config import (
    CopyActions,
    DataModificationActions,
    DataModificationStep,
    FieldCopyConfig,
    FilterConfig,
    FilterSource,
    IgnoreFilterSource,
    MapKeys,
    ModelCopyConfig,
    find_map_key_conflicts,
    get_queryset_for_model_config,
    map_key,
    map_key_labels,
)
from django_copyist.copy_request import AbortReason, CopyRequest, CopyResult

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _required(value: T | None, name: str) -> T:
    """
    Narrow an optional config attribute that ``__post_init__`` guarantees for the action.
    """
    if value is None:
        raise ValueError(f"{name} is required for this action, but it is not set")
    return value


def filter_config_of(field_copy_config: FieldCopyConfig) -> FilterConfig:
    return _required(field_copy_config.filter_config, "filter_config")


FieldSetToFilterMap = dict[str, str | None]
SetToFilterMap = dict[str, dict[str, FieldSetToFilterMap]]
OutputMap = dict[str, dict[str, Any]]
ValidationAffectedMap = dict[str, list[Any]]
IgnoredMap = dict[str, list[Any]]


@dataclass
class SubstituteCondition:
    """
    Intermediate model storing single condition for matching origin and substitute instances
    """

    filter_field_name: str
    filter_field_value: Any


@dataclass
class M2MCopyIntent:
    """
    Intermediate model storing intent for copying data for many to many relation
    """

    field_name: str
    related_id_list: list[Any]
    backward_id_key: str
    forward_id_key: str
    through_model: type[Model]
    from_model: type[Model]
    to_model: type[Model]
    use_copied_related_instances: bool
    use_set_to_filter_values: bool

    def __post_init__(self) -> None:
        for key in (self.backward_id_key, self.forward_id_key):
            if getattr(self.through_model, key, None) is None:
                raise ValueError(
                    f"Not found key {key} on through model {self.through_model._meta.label}"
                )


@dataclass
class CopyIntent:
    """
    Intermediate model storing intent for copying data for instance of model
    """

    origin: Model
    copy_data: dict[str, Any] = field(default_factory=dict)
    m2m_copy_intent_list: list[M2MCopyIntent] = field(default_factory=list)

    copied: Model | None = None

    def __repr__(self) -> str:
        return (
            f"CopyIntent: {self.origin.__class__._meta.label}\n"
            f"Copied: {bool(self.copied)}\n"
            f"m2m: {self.m2m_copy_intent_list}"
        )


@dataclass
class CopyistConfig:
    """
    This is the root copy configuration that contains a list of ModelCopyConfig.

    :ivar list[ModelCopyConfig] model_configs: The list of model configurations.
    :ivar MapKeys map_keys: How models are keyed in ``output_map``, ``ignored_map`` and
        ``set_to_filter_map``. ``MODEL_NAME`` (default) uses the class name, for example
        ``"Company"``. If two models in the config share a class name, the copy raises
        ``ImproperlyConfigured``: switch to ``LABEL`` (``"demo.Company"``).
    """

    model_configs: list[ModelCopyConfig]
    map_keys: MapKeys = MapKeys.MODEL_NAME


@dataclass
class ParentFilter:
    """
    Restricts a query to rows whose ``field`` value is in ``ids``.

    The engine evaluates it in chunks, so ``ids`` may be longer than the
    backend limit of query parameters.
    """

    field: str
    ids: list[Any]

    def as_q(self) -> Q:
        return Q(**{f"{self.field}__in": self.ids})


@dataclass
class IgnoreEvaluation:
    """
    Intermediate model storing intent after validation to resolve ignore conditions
    """

    model_config: ModelCopyConfig
    original_extra_filter: Q | None
    parent_filter: ParentFilter | None = None


class Copyist:
    """
    The main class responsible for copying Django model instances based on the provided
    configuration.

    :param CopyRequest copy_request: The copy request object containing the configuration and
        input data for the copy operation.

    :ivar CopyRequest request: The copy request object containing the configuration
        and input data for the copy operation.
    :ivar CopyistConfig config: The configuration for the copy operation.
    :ivar dict input_data: The input data for the copy operation.
    """

    def __init__(self, copy_request: CopyRequest):
        self.request = copy_request
        self.config = copy_request.config
        self.input_data = copy_request.input_data
        self.using = copy_request.using
        self.batch_size = copy_request.batch_size

        self._set_to_filter_map: SetToFilterMap | None = None
        self._validation_affected_map: ValidationAffectedMap | None = None
        self._ignored_map: IgnoredMap | None = None
        self._ignore_conditions_to_resolve: list[IgnoreEvaluation] | None = None

    def _manager(self, model: type[Model]) -> Manager[Model]:
        """
        Default manager of ``model`` bound to the requested database alias.
        """
        return model._default_manager.db_manager(self.using)

    def _key(self, model: type[Model]) -> str:
        """
        Key of ``model`` in output, ignored and set-to-filter maps.

        ``"Company"`` by default, ``"demo.Company"`` with ``MapKeys.LABEL``.
        """
        return map_key(model, self.config.map_keys)

    def _write_db(self, model: type[Model]) -> str:
        return self.using or router.db_for_write(model)

    @property
    def set_to_filter_map(self) -> SetToFilterMap:
        if self._set_to_filter_map is None:
            raise AttributeError("set_to_filter_map referenced before validation")
        return self._set_to_filter_map

    @property
    def validation_affected_map(self) -> ValidationAffectedMap:
        if self._validation_affected_map is None:
            raise AttributeError("validation_affected_map referenced before validation")
        return self._validation_affected_map

    @property
    def _ignore_conditions(self) -> list[IgnoreEvaluation]:
        if self._ignore_conditions_to_resolve is None:
            raise AttributeError("ignore conditions referenced before validation")
        return self._ignore_conditions_to_resolve

    @property
    def ignored_map(self) -> IgnoredMap:
        if self._ignored_map is None:
            raise AttributeError("ignored_map referenced before validation")
        return self._ignored_map

    def _filter_in(
        self, queryset: QuerySet[Model], lookup: str, values: Iterable[Any]
    ) -> list[Model]:
        """
        Evaluate ``queryset.filter(**{lookup: values})`` for an ``__in`` lookup.

        Splits ``values`` into chunks that fit the backend limit of query parameters
        (999 on SQLite), so any number of values works. Removes duplicate values and
        duplicate rows.
        """
        unique_values = list(dict.fromkeys(values))
        if not unique_values:
            return []
        limit = connections[queryset.db].features.max_query_params
        chunk_size = len(unique_values) if limit is None else max(limit - 100, 100)
        if len(unique_values) <= chunk_size:
            return list(queryset.filter(**{lookup: unique_values}))

        rows: dict[Any, Model] = {}
        for start in range(0, len(unique_values), chunk_size):
            chunk = unique_values[start : start + chunk_size]
            for row in queryset.filter(**{lookup: chunk}):
                rows.setdefault(row.pk, row)
        return list(rows.values())

    def _get_instances_for_model_config(
        self,
        model_config: ModelCopyConfig,
        extra_filters: Q | None,
        parent_filter: ParentFilter | None = None,
    ) -> list[Model]:
        queryset = get_queryset_for_model_config(
            model_config=model_config,
            extra_filters=extra_filters,
            input_data=self.input_data,
            using=self.using,
            scoped_by_caller=parent_filter is not None,
        )
        if parent_filter is None:
            return list(queryset)
        return self._filter_in(queryset, f"{parent_filter.field}__in", parent_filter.ids)

    def _get_referenced_instance_list(
        self,
        model_config: ModelCopyConfig,
        field_name: str,
        field_copy_config: FieldCopyConfig,
        instance_list: list[Model],
    ) -> list[Model]:
        field_link = getattr(model_config.model, field_name, None)
        if not field_link:
            raise ValueError(
                f"Field {field_name} was declared in {model_config.model._meta.label} "
                f"config, but not present on model"
            )
        if not isinstance(field_link, ForwardManyToOneDescriptor | ManyToManyDescriptor):
            raise ValueError(
                f"Expected ForeignKeyField or ManyToManyField field on {field_name} for "
                f"SET_TO_FILTER config, but got {field_link.__class__.__name__}"
            )

        if isinstance(field_link, ManyToManyDescriptor):
            if field_link.reverse:
                relation_key = field_link.field.name
            else:
                relation_key = field_link.field.related_query_name()
            filter_key = f"{relation_key}__pk"

            return self._filter_in(
                self._manager(_required(field_copy_config.reference_to, "reference_to")).distinct(),
                f"{filter_key}__in",
                [i.pk for i in instance_list],
            )
        elif isinstance(field_link, ForwardManyToOneDescriptor):
            id_key_field_name = field_link.field.attname
            referenced_id_values = [
                getattr(instance, id_key_field_name)
                for instance in instance_list
                if getattr(instance, id_key_field_name) is not None
            ]
            return self._filter_in(
                self._manager(_required(field_copy_config.reference_to, "reference_to")).all(),
                "pk__in",
                referenced_id_values,
            )
        else:
            raise ValueError(
                f"Expected ForeignKeyField or ManyToManyField field on {field_name} for "
                f"SET_TO_FILTER config, but got {field_link.__class__.__name__}"
            )

    def _get_substitute_instance_list(
        self,
        field_copy_config: FieldCopyConfig,
        referenced_instance_list: list[Model],
    ) -> list[Model]:
        referenced_model = _required(field_copy_config.reference_to, "reference_to")
        substitutes_query = self._manager(referenced_model).all()
        for (
            filter_field_name,
            filter_config,
        ) in (filter_config_of(field_copy_config).filters or {}).items():
            if filter_config.source == FilterSource.FROM_INPUT:
                filter_value = self.input_data.get(_required(filter_config.key, "key"))
                if filter_value is None:
                    raise ValueError(
                        f"Filter {filter_field_name} was declared, "
                        f"but value for {filter_config.key} not found in input_data"
                    )
                substitutes_query = substitutes_query.filter(**{filter_field_name: filter_value})
            elif filter_config.source == FilterSource.FROM_ORIGIN:
                shared_values = [getattr(i, filter_field_name) for i in referenced_instance_list]
                substitutes_query = substitutes_query.filter(
                    **{f"{filter_field_name}__in": list(dict.fromkeys(shared_values))}
                )

        substitutes_instance_list = list(substitutes_query)
        return substitutes_instance_list

    def _match_referenced_with_substitutes(
        self,
        field_copy_config: FieldCopyConfig,
        referenced_instance_list: list[Model],
        substitute_instance_list: list[Model],
    ) -> FieldSetToFilterMap:
        field_set_to_filter_map: dict[str, str | None] = {}
        take_from_origin_filters = {
            k: v
            for k, v in (filter_config_of(field_copy_config).filters or {}).items()
            if v.source == FilterSource.FROM_ORIGIN
        }
        for referenced_instance in referenced_instance_list:
            substitute_conditions = []
            for filter_field_name in take_from_origin_filters.keys():
                substitute_conditions.append(
                    SubstituteCondition(
                        filter_field_name=filter_field_name,
                        filter_field_value=getattr(referenced_instance, filter_field_name),
                    )
                )

            substitute_instance = next(
                (
                    i
                    for i in substitute_instance_list
                    if all(
                        [
                            getattr(i, c.filter_field_name) == c.filter_field_value
                            for c in substitute_conditions
                        ]
                    )
                ),
                None,
            )
            if substitute_instance:
                field_set_to_filter_map[str(referenced_instance.pk)] = str(substitute_instance.pk)
            else:
                field_set_to_filter_map[str(referenced_instance.pk)] = None

        return field_set_to_filter_map

    def _get_field_set_to_filter_map_for_filters(
        self,
        field_copy_config: FieldCopyConfig,
        referenced_instance_list: list[Model],
    ) -> FieldSetToFilterMap:
        substitute_instance_list = self._get_substitute_instance_list(
            field_copy_config=field_copy_config,
            referenced_instance_list=referenced_instance_list,
        )

        field_set_to_filter_map = self._match_referenced_with_substitutes(
            field_copy_config=field_copy_config,
            referenced_instance_list=referenced_instance_list,
            substitute_instance_list=substitute_instance_list,
        )
        return field_set_to_filter_map

    def _execute_set_to_filter_config_validation(
        self,
        model_config: ModelCopyConfig,
        field_name: str,
        field_copy_config: FieldCopyConfig,
        set_to_filter_map: SetToFilterMap,
        instance_list: list[Model],
    ) -> None:
        referenced_instance_list = self._get_referenced_instance_list(
            model_config=model_config,
            field_name=field_name,
            field_copy_config=field_copy_config,
            instance_list=instance_list,
        )
        filter_config = filter_config_of(field_copy_config)
        if filter_config.filters:
            field_set_to_filter_map = self._get_field_set_to_filter_map_for_filters(
                field_copy_config=field_copy_config,
                referenced_instance_list=referenced_instance_list,
            )
        elif filter_config.filter_func:
            field_set_to_filter_map = filter_config.filter_func(
                field_copy_config=field_copy_config,
                field_name=field_name,
                input_data=self.input_data,
                instance_list=instance_list,
                model_config=model_config,
                referenced_instance_list=referenced_instance_list,
                set_to_filter_map=set_to_filter_map,
            )
        else:
            raise ValueError("Incorrect filter config")

        if self._key(model_config.model) not in set_to_filter_map:
            set_to_filter_map[self._key(model_config.model)] = {}
        set_to_filter_map[self._key(model_config.model)][field_name] = field_set_to_filter_map

    def _execute_make_copy_config_validation(
        self,
        model_config: ModelCopyConfig,
        field_copy_config: FieldCopyConfig,
        field_name: str,
        set_to_filter_map: SetToFilterMap,
        instance_list: list[Model],
    ) -> None:
        field_link = getattr(model_config.model, field_name, None)
        if not field_link:
            raise ValueError(
                f"Field {field_name} was declared in {model_config.model._meta.label} "
                f"config, but not present on model"
            )

        if not isinstance(field_link, ReverseManyToOneDescriptor):
            raise ValueError(
                f"Expected Many to One field on {field_name} for "
                f"MAKE_COPY config, but got {field_link.__class__.__name__}"
            )

        relation_field_name = field_link.field.attname

        self._run_validation_for_model(
            model_config=_required(field_copy_config.copy_with_config, "copy_with_config"),
            set_to_filter_map=set_to_filter_map,
            parent_filter=ParentFilter(relation_field_name, [i.pk for i in instance_list]),
        )

    def _get_extra_filters_for_compound_actions(
        self, model_config: ModelCopyConfig, affected_map: ValidationAffectedMap
    ) -> Q:
        """
        If there are any non nullable filters - we can just use them as mandatory,
        and all nullable filters could be used with OR filter on null value, so we
        will get all entities that references updated values

        If there are only nullable fields - we have to take more precise approach
        of combinations of filters so at least one field is filled with updated values,
        otherwise result filters will also query objects where all fields are NULL,
        which should not be copied
        """
        extra_filters = Q()

        fk_fields_to_filter = []
        nullable_fields_to_filter = []

        for field_name, field_copy_config in model_config.field_copy_actions.items():
            if field_copy_config.action != CopyActions.UPDATE_TO_COPIED:
                continue

            if _required(field_copy_config.reference_to, "reference_to") == model_config.model:
                continue

            field_link = getattr(model_config.model, field_name)
            if isinstance(field_link, ForwardManyToOneDescriptor):
                if field_link.field.null:
                    nullable_fields_to_filter.append(field_name)
                else:
                    fk_fields_to_filter.append(field_name)
            elif isinstance(field_link, ManyToManyDescriptor):
                nullable_fields_to_filter.append(field_name)
            else:
                raise ValueError(
                    f"Expected m2m or fk on field {field_name} on model "
                    f"{model_config.model._meta.label}, got {field_link.__class__.__name__}"
                )

        for field_name in fk_fields_to_filter:
            field_copy_config = model_config.field_copy_actions[field_name]
            copied_referenced_id_list = affected_map.get(
                self._key(_required(field_copy_config.reference_to, "reference_to"))
            )
            if not copied_referenced_id_list:
                continue

            extra_filters &= Q(**{f"{field_name}__in": copied_referenced_id_list}) | Q(
                **{field_name: None}
            )

        non_nullable_filters_were_used = bool(extra_filters)

        if non_nullable_filters_were_used:
            for field_name in nullable_fields_to_filter:
                field_copy_config = model_config.field_copy_actions[field_name]
                copied_referenced_id_list = affected_map.get(
                    self._key(_required(field_copy_config.reference_to, "reference_to"))
                )
                if not copied_referenced_id_list:
                    continue

                extra_filters &= Q(**{f"{field_name}__in": copied_referenced_id_list}) | Q(
                    **{field_name: None}
                )
        else:
            result_nullable_filter = Q()
            for field_name in nullable_fields_to_filter:
                field_copy_config = model_config.field_copy_actions[field_name]
                copied_referenced_id_list = affected_map.get(
                    self._key(_required(field_copy_config.reference_to, "reference_to"))
                )
                if not copied_referenced_id_list:
                    continue
                combination_filter = Q(**{f"{field_name}__in": copied_referenced_id_list})
                for other_field in [f for f in nullable_fields_to_filter if f != field_name]:
                    other_field_copy_config = model_config.field_copy_actions[other_field]
                    copied_other_referenced_id_list = affected_map.get(
                        self._key(_required(other_field_copy_config.reference_to, "reference_to"))
                    )
                    if not copied_other_referenced_id_list:
                        continue

                    combination_filter &= Q(
                        **{f"{other_field}__in": copied_other_referenced_id_list}
                    ) | Q(**{other_field: None})
                result_nullable_filter |= combination_filter

            extra_filters &= result_nullable_filter

        return extra_filters

    def _evaluate_ignored_by_filters(
        self,
        model_config: ModelCopyConfig,
        set_to_filter_map: SetToFilterMap,
        model_extra_filter: Q | None,
        parent_filter: ParentFilter | None,
    ) -> list[Model]:
        ignore_filter = Q()
        ignore_condition = _required(model_config.ignore_condition, "ignore_condition")
        for condition in ignore_condition.filter_conditions or []:
            if condition.filter_source == IgnoreFilterSource.UNMATCHED_SET_TO_FILTER_VALUES:
                value_model_map = set_to_filter_map[
                    self._key(condition.set_to_filter_origin_model)
                ].get(condition.set_to_filter_field_name)
                if not value_model_map:
                    continue
                unmatched_id_list = [k for k, v in value_model_map.items() if v is None]
                if not unmatched_id_list:
                    continue
                ignore_filter |= Q(**{condition.filter_name: unmatched_id_list})

        if not ignore_filter:
            return []

        if model_extra_filter and parent_filter is None:
            ignore_filter &= model_extra_filter

        ignored_values = self._get_instances_for_model_config(
            model_config, extra_filters=ignore_filter, parent_filter=parent_filter
        )
        return ignored_values

    def _evaluate_ignored(
        self,
        model_config: ModelCopyConfig,
        set_to_filter_map: SetToFilterMap,
        model_extra_filter: Q | None,
        parent_filter: ParentFilter | None = None,
    ) -> None:
        if not model_config.ignore_condition:
            return

        ignore_condition = model_config.ignore_condition
        if ignore_condition.filter_conditions:
            ignored_values = self._evaluate_ignored_by_filters(
                model_config=model_config,
                set_to_filter_map=set_to_filter_map,
                model_extra_filter=model_extra_filter,
                parent_filter=parent_filter,
            )
        elif ignore_condition.ignore_func:
            ignored_values = ignore_condition.ignore_func(
                model_config=model_config,
                set_to_filter_map=set_to_filter_map,
                model_extra_filter=model_extra_filter,
                ignored_map=self.ignored_map,
                input_data=self.input_data,
            )
        else:
            raise ValueError("No ignore func or filter condition on ignore condition")

        if not ignored_values:
            return
        self.ignored_map[self._key(model_config.model)] = list({i.pk for i in ignored_values})

    def _run_validation_for_model(
        self,
        model_config: ModelCopyConfig,
        set_to_filter_map: SetToFilterMap,
        model_extra_filters: Q | None = None,
        parent_filter: ParentFilter | None = None,
    ) -> SetToFilterMap:
        instance_list = self._get_instances_for_model_config(
            model_config, extra_filters=model_extra_filters, parent_filter=parent_filter
        )
        if self._key(model_config.model) in self.validation_affected_map:
            raise ValueError(
                f"Model {model_config.model._meta.label} has been configured for copy several times"
            )
        self.validation_affected_map[self._key(model_config.model)] = [i.pk for i in instance_list]

        for field_name, field_copy_config in model_config.field_copy_actions.items():
            if field_copy_config.action == CopyActions.SET_TO_FILTER:
                self._execute_set_to_filter_config_validation(
                    model_config=model_config,
                    field_copy_config=field_copy_config,
                    field_name=field_name,
                    set_to_filter_map=set_to_filter_map,
                    instance_list=instance_list,
                )
            elif field_copy_config.action == CopyActions.MAKE_COPY:
                self._execute_make_copy_config_validation(
                    model_config=model_config,
                    field_copy_config=field_copy_config,
                    field_name=field_name,
                    set_to_filter_map=set_to_filter_map,
                    instance_list=instance_list,
                )

        for compound_config in model_config.compound_copy_actions:
            extra_filters = self._get_extra_filters_for_compound_actions(
                model_config=compound_config, affected_map=self.validation_affected_map
            )
            if not extra_filters:
                continue
            self._run_validation_for_model(
                model_config=compound_config,
                set_to_filter_map=set_to_filter_map,
                model_extra_filters=extra_filters,
            )

        if model_config.ignore_condition:
            self._ignore_conditions.append(
                IgnoreEvaluation(
                    model_config=model_config,
                    # Ignore functions receive the scope of the model as a Q object.
                    original_extra_filter=(
                        parent_filter.as_q() if parent_filter else model_extra_filters
                    ),
                    parent_filter=parent_filter,
                )
            )

        return set_to_filter_map

    def _resolve_ignore_conditions(self, set_to_filter_map: SetToFilterMap) -> None:
        for condition in self._ignore_conditions:
            self._evaluate_ignored(
                model_config=condition.model_config,
                set_to_filter_map=set_to_filter_map,
                model_extra_filter=condition.original_extra_filter,
                parent_filter=condition.parent_filter,
            )

    def _check_map_key_conflicts(self) -> None:
        if self.config.map_keys != MapKeys.MODEL_NAME:
            return
        conflicts = find_map_key_conflicts(self.config.model_configs)
        if conflicts:
            details = "; ".join(
                f"{name}: {', '.join(labels)}" for name, labels in conflicts.items()
            )
            raise ImproperlyConfigured(
                f"Several models in this config share a class name ({details}), so "
                f"result maps keyed by class name would mix them. Pass "
                f"CopyistConfig(..., map_keys=MapKeys.LABEL) or "
                f"run_copy(..., map_keys=MapKeys.LABEL) to key maps by 'app_label.Model'."
            )

    def validate_config(self) -> None:
        self._check_map_key_conflicts()
        set_to_filter_map: SetToFilterMap = {}
        self._validation_affected_map = {}
        self._ignored_map = {}
        self._ignore_conditions_to_resolve = []

        for model_config in self.config.model_configs:
            if not model_config.filter_field_to_input_key:
                raise ValueError(
                    f"Root config must describe filter_filed_to_input_key map, "
                    f"to narrow the query on {model_config.model._meta.label}"
                )
            self._run_validation_for_model(
                model_config=model_config,
                set_to_filter_map=set_to_filter_map,
            )
        self._resolve_ignore_conditions(set_to_filter_map)
        self._set_to_filter_map = set_to_filter_map

    @staticmethod
    def _get_forward_fk_attname(model_class: type[Model], field_name: str) -> str | None:
        """
        Column attribute name (``project_id``) if ``field_name`` is a forward FK or
        one-to-one field (``project``), else None.
        """
        descriptor = getattr(model_class, field_name, None)
        if isinstance(descriptor, ForwardManyToOneDescriptor):
            attname: str = descriptor.field.attname
            return attname
        return None

    def _evaluate_take_from_origin_field_values(
        self,
        model_class: type[Model],
        field_name: str,
        copy_intent_list: list[CopyIntent],
    ) -> None:
        class_field = getattr(model_class, field_name, None)
        if isinstance(class_field, ManyToManyDescriptor):
            referenced_model = (
                class_field.field.model if class_field.reverse else class_field.field.related_model
            )
            # One call handles every instance: it reads the through table once.
            self._evaluate_m2m_field_values(
                field_name=field_name,
                field_link=class_field,
                instance_id_list=[c.origin.pk for c in copy_intent_list],
                copy_intent_list=copy_intent_list,
                referenced_model=referenced_model,
                use_copied_related_instances=False,
            )
            return

        # Copy the FK column, not the related object: reading the related object
        # costs one query per instance.
        source_name = self._get_forward_fk_attname(model_class, field_name) or field_name
        for copy_intent in copy_intent_list:
            try:
                origin_value = getattr(copy_intent.origin, source_name)
            except AttributeError as e:
                raise ValueError(
                    f"{field_name} declared for copy from origin, "
                    f"but field not found on model {model_class._meta.label}"
                ) from e

            copy_intent.copy_data[source_name] = origin_value

    def _evaluate_take_from_input_field_values(
        self,
        model_class: type[Model],
        field_name: str,
        copy_intent_list: list[CopyIntent],
        input_key: str,
    ) -> None:
        if self.input_data.get(input_key) is None:
            raise ValueError(f"No {input_key} in input_data")
        input_value = self.input_data[input_key]

        target_name = field_name
        fk_attname = self._get_forward_fk_attname(model_class, field_name)
        if fk_attname and not isinstance(input_value, Model):
            # Accept a primary key value for a FK field.
            target_name = fk_attname

        for copy_intent in copy_intent_list:
            copy_intent.copy_data[target_name] = input_value

    def _get_m2m_relation_map(
        self,
        field_link: ManyToManyDescriptor[Any],
        instance_id_list: list[Any],
        backward_filter_key: str,
        m2m_backward_id_field_name: str,
        m2m_forward_id_field_name: str,
    ) -> dict[str, list[str]]:
        through_model = field_link.through
        through_records = self._filter_in(
            self._manager(through_model).all(), backward_filter_key, instance_id_list
        )
        m2m_map: dict[str, list[str]] = {}
        for record in through_records:
            origin_id = getattr(record, m2m_backward_id_field_name)
            if str(origin_id) not in m2m_map:
                m2m_map[str(origin_id)] = []
            linked_id = getattr(record, m2m_forward_id_field_name)
            m2m_map[str(origin_id)].append(str(linked_id))

        return m2m_map

    def _save_m2m_fields_values(
        self,
        copy_intent_list: list[CopyIntent],
        field_name: str,
        m2m_map: dict[str, list[str]],
        referenced_model: type[Model],
        through_model: type[Model],
        m2m_forward_id_field_name: str,
        m2m_backward_id_field_name: str,
        use_copied_related_instances: bool,
        use_set_to_filter_values: bool,
    ) -> None:
        for copy_intent in copy_intent_list:
            related_id_list = m2m_map.get(str(copy_intent.origin.pk))
            if related_id_list:
                copy_intent.m2m_copy_intent_list.append(
                    M2MCopyIntent(
                        field_name=field_name,
                        related_id_list=related_id_list,
                        through_model=through_model,
                        forward_id_key=m2m_forward_id_field_name,
                        backward_id_key=m2m_backward_id_field_name,
                        from_model=copy_intent.origin.__class__,
                        to_model=referenced_model,
                        use_copied_related_instances=use_copied_related_instances,
                        use_set_to_filter_values=use_set_to_filter_values,
                    )
                )

    def _evaluate_m2m_field_values(
        self,
        field_name: str,
        field_link: ManyToManyDescriptor[Any],
        instance_id_list: list[Any],
        copy_intent_list: list[CopyIntent],
        referenced_model: type[Model],
        use_copied_related_instances: bool = False,
        use_set_to_filter_values: bool = False,
    ) -> None:
        if use_copied_related_instances and use_set_to_filter_values:
            raise ValueError(
                "Both use_copied_related_instances and use_set_to_filter_values are set to True"
            )
        if field_link.reverse:
            backward_relation_key = field_link.field.m2m_reverse_field_name()
            forward_relation_key = field_link.field.m2m_field_name()
        else:
            backward_relation_key = field_link.field.m2m_field_name()
            forward_relation_key = field_link.field.m2m_reverse_field_name()
        backward_filter_key = f"{backward_relation_key}_id__in"
        m2m_forward_id_field_name = f"{forward_relation_key}_id"
        m2m_backward_id_field_name = f"{backward_relation_key}_id"

        m2m_map = self._get_m2m_relation_map(
            field_link=field_link,
            backward_filter_key=backward_filter_key,
            m2m_backward_id_field_name=m2m_backward_id_field_name,
            m2m_forward_id_field_name=m2m_forward_id_field_name,
            instance_id_list=instance_id_list,
        )

        self._save_m2m_fields_values(
            m2m_map=m2m_map,
            copy_intent_list=copy_intent_list,
            field_name=field_name,
            referenced_model=referenced_model,
            m2m_backward_id_field_name=m2m_backward_id_field_name,
            m2m_forward_id_field_name=m2m_forward_id_field_name,
            through_model=field_link.through,
            use_copied_related_instances=use_copied_related_instances,
            use_set_to_filter_values=use_set_to_filter_values,
        )

    def _evaluate_reverse_fk_field_values(
        self,
        field_link: ForwardManyToOneDescriptor[Any],
        model_output_map: dict[str, str],
        copy_intent_list: list[CopyIntent],
        referenced_model: type[Model],
    ) -> None:
        id_field_name = field_link.field.attname
        for copy_intent in copy_intent_list:
            referenced_instance_id = getattr(copy_intent.origin, id_field_name)
            if referenced_instance_id is None:
                copy_id = None
            else:
                copy_id = model_output_map.get(str(referenced_instance_id))
                if not copy_id:
                    raise ValueError(
                        f"Copy of {referenced_model._meta.label} with id {referenced_instance_id} "
                        f"was not found in output map"
                    )

            copy_intent.copy_data[id_field_name] = copy_id

    def _evaluate_update_to_copied_field_values(
        self,
        model_class: type[Model],
        field_copy_config: FieldCopyConfig,
        model_output_map: dict[str, str],
        field_name: str,
        instance_list: list[Model],
        copy_intent_list: list[CopyIntent],
    ) -> None:
        referenced_model = _required(field_copy_config.reference_to, "reference_to")

        field_link = getattr(model_class, field_name)
        if not isinstance(field_link, ForwardManyToOneDescriptor | ManyToManyDescriptor):
            raise ValueError(
                f"Expected ManyToOne or ManyToMany field on {field_name} for "
                f"UPDATE_TO_COPIED config, but got "
                f"{field_link.__class__.__name__}, on {model_class._meta.label}"
            )

        if isinstance(field_link, ManyToManyDescriptor) and field_link.reverse:
            real_referenced_model = field_link.field.model
        else:
            real_referenced_model = field_link.field.related_model

        if real_referenced_model != referenced_model:
            raise ValueError(
                f'"{referenced_model._meta.label}" was referenced from '
                f'{model_class._meta.label} by field "{field_name}", '
                f'but "{real_referenced_model._meta.label}" was found by that name'
            )

        if isinstance(field_link, ManyToManyDescriptor):
            self._evaluate_m2m_field_values(
                field_name=field_name,
                field_link=field_link,
                instance_id_list=[i.pk for i in instance_list],
                copy_intent_list=copy_intent_list,
                referenced_model=referenced_model,
                use_copied_related_instances=True,
            )
        elif isinstance(field_link, ForwardManyToOneDescriptor):
            self._evaluate_reverse_fk_field_values(
                field_link=field_link,
                model_output_map=model_output_map,
                copy_intent_list=copy_intent_list,
                referenced_model=referenced_model,
            )

    def _evaluate_set_to_filter_field_values(
        self,
        model_class: type[Model],
        field_copy_config: FieldCopyConfig,
        field_name: str,
        copy_intent_list: list[CopyIntent],
    ) -> None:
        field_link = getattr(model_class, field_name)
        id_field_name = field_link.field.attname
        referenced_model = _required(field_copy_config.reference_to, "reference_to")
        model_set_to_filter_map = self.set_to_filter_map[self._key(model_class)].get(field_name)

        if isinstance(field_link, ManyToManyDescriptor):
            # One call handles every instance: it reads the through table once.
            self._evaluate_m2m_field_values(
                field_name=field_name,
                field_link=field_link,
                instance_id_list=[c.origin.pk for c in copy_intent_list],
                copy_intent_list=copy_intent_list,
                referenced_model=referenced_model,
                use_set_to_filter_values=True,
            )
            return

        for copy_intent in copy_intent_list[:]:
            origin_related_id = getattr(copy_intent.origin, id_field_name)
            if origin_related_id is None:
                substitute_id = None
            else:
                if not model_set_to_filter_map:
                    raise RuntimeError(
                        f"No model filters are ready for "
                        f"{referenced_model._meta.label} in {field_name}"
                    )

                substitute_id = model_set_to_filter_map[str(origin_related_id)]
                if substitute_id is None:
                    copy_intent_list.remove(copy_intent)
            copy_intent.copy_data[id_field_name] = substitute_id

    def _evaluate_field_values(
        self,
        field_name: str,
        field_copy_config: FieldCopyConfig,
        model_class: type[Model],
        copy_intent_list: list[CopyIntent],
        instance_list: list[Model],
        output_map: dict[str, dict[str, str]],
    ) -> None:
        if field_copy_config.action == CopyActions.MAKE_COPY:
            return
        elif field_copy_config.action == CopyActions.TAKE_FROM_ORIGIN:
            self._evaluate_take_from_origin_field_values(
                field_name=field_name,
                model_class=model_class,
                copy_intent_list=copy_intent_list,
            )
        elif field_copy_config.action == CopyActions.TAKE_FROM_INPUT:
            self._evaluate_take_from_input_field_values(
                model_class=model_class,
                field_name=field_name,
                copy_intent_list=copy_intent_list,
                input_key=_required(field_copy_config.input_key, "input_key"),
            )
        elif field_copy_config.action == CopyActions.UPDATE_TO_COPIED:
            referenced_model = _required(field_copy_config.reference_to, "reference_to")
            model_output_map = output_map.get(self._key(referenced_model), {})

            self._evaluate_update_to_copied_field_values(
                model_class=model_class,
                field_copy_config=field_copy_config,
                model_output_map=model_output_map,
                field_name=field_name,
                instance_list=instance_list,
                copy_intent_list=copy_intent_list,
            )
        elif field_copy_config.action == CopyActions.SET_TO_FILTER:
            self._evaluate_set_to_filter_field_values(
                copy_intent_list=copy_intent_list,
                field_copy_config=field_copy_config,
                field_name=field_name,
                model_class=model_class,
            )
        else:
            raise NotImplementedError(f"Unknown action {field_copy_config.action}")

    def _execute_delete_by_filter_step(
        self, model_config: ModelCopyConfig, step: DataModificationStep
    ) -> None:
        filters = {}
        for filter_field, input_key in (step.filter_field_to_input_key or {}).items():
            if self.input_data.get(input_key) is None:
                raise ValueError(
                    f"DELETE_BY_FILTER step on {model_config.model._meta.label} needs "
                    f"{input_key} in input_data"
                )
            filters[filter_field] = self.input_data[input_key]
        self._manager(model_config.model).filter(**filters).delete()

    def run_data_preparation(self, model_config: ModelCopyConfig, output_map: OutputMap) -> None:
        for step in model_config.data_preparation_steps:
            if step.action == DataModificationActions.DELETE_BY_FILTER:
                self._execute_delete_by_filter_step(model_config, step)
            elif step.action == DataModificationActions.EXECUTE_FUNC:
                _required(step.func, "func")(
                    model_config=model_config,
                    input_data=self.input_data,
                    set_to_filter_map=self.set_to_filter_map,
                    output_map=output_map,
                )

    def run_postcopy_steps(
        self,
        model_config: ModelCopyConfig,
        output_map: OutputMap,
        copy_intent_list: list[CopyIntent],
    ) -> None:
        for step in model_config.postcopy_steps:
            if step.action == DataModificationActions.DELETE_BY_FILTER:
                self._execute_delete_by_filter_step(model_config, step)
            elif step.action == DataModificationActions.EXECUTE_FUNC:
                _required(step.func, "func")(
                    model_config=model_config,
                    input_data=self.input_data,
                    set_to_filter_map=self.set_to_filter_map,
                    output_map=output_map,
                    copy_intent_list=copy_intent_list,
                )

    def _get_copied_ids_from_output_map(
        self,
        model_class: type[Model],
        m2m_copy_intent: M2MCopyIntent,
        output_map: OutputMap,
    ) -> list[str]:
        copied_related_id_list = []
        for related_id in m2m_copy_intent.related_id_list:
            related_output_map = output_map.get(self._key(m2m_copy_intent.to_model))
            if not related_output_map:
                raise ValueError(
                    f"{m2m_copy_intent.to_model._meta.label} referenced from "
                    f"{model_class._meta.label} before any copies were made"
                )
            copied_related_id = related_output_map.get(related_id)
            if not copied_related_id:
                raise ValueError(
                    f"Copy of {m2m_copy_intent.to_model._meta.label} with pk {related_id} "
                    f"was not found in output map"
                )
            copied_related_id_list.append(copied_related_id)
        return copied_related_id_list

    def _create_m2m_relations_for_update_to_copied(
        self,
        model_class: type[Model],
        copy_intent_list: list[CopyIntent],
        output_map: OutputMap,
    ) -> None:
        m2m_relations_to_create: dict[type[Model], list[Model]] = {}

        for copy_intent in copy_intent_list:
            for m2m_copy_intent in copy_intent.m2m_copy_intent_list:
                if m2m_copy_intent.through_model not in m2m_relations_to_create:
                    m2m_relations_to_create[m2m_copy_intent.through_model] = []

                if m2m_copy_intent.use_copied_related_instances:
                    related_id_list_to_create = self._get_copied_ids_from_output_map(
                        model_class=model_class,
                        m2m_copy_intent=m2m_copy_intent,
                        output_map=output_map,
                    )
                elif m2m_copy_intent.use_set_to_filter_values:
                    field_set_to_filter_map = self.set_to_filter_map[
                        self._key(m2m_copy_intent.from_model)
                    ][m2m_copy_intent.field_name]
                    related_id_list_to_create = [
                        substitute_id
                        for related_id in m2m_copy_intent.related_id_list
                        if (substitute_id := field_set_to_filter_map.get(related_id))
                    ]
                else:
                    related_id_list_to_create = m2m_copy_intent.related_id_list

                m2m_relations_to_create[m2m_copy_intent.through_model] += [
                    m2m_copy_intent.through_model(
                        **{
                            m2m_copy_intent.backward_id_key: _required(
                                copy_intent.copied, "copied"
                            ).pk,
                            m2m_copy_intent.forward_id_key: related_id,
                        }
                    )
                    for related_id in related_id_list_to_create
                ]

        for model, to_create in m2m_relations_to_create.items():
            self._manager(model).bulk_create(to_create, batch_size=self.batch_size)

    def _execute_copy_for_make_copy_fields(
        self,
        model_config: ModelCopyConfig,
        copy_intent_list: list[CopyIntent],
        output_map: OutputMap,
    ) -> None:
        # Children of origin rows that were not copied (unmatched SET_TO_FILTER
        # values) are skipped.
        copied_origin_ids = [c.origin.pk for c in copy_intent_list]
        for field_name, field_copy_config in model_config.field_copy_actions.items():
            if field_copy_config.action != CopyActions.MAKE_COPY:
                continue

            field_link = getattr(model_config.model, field_name)
            relation_field_name = field_link.field.attname
            self.copy_model(
                model_config=_required(field_copy_config.copy_with_config, "copy_with_config"),
                output_map=output_map,
                parent_filter=ParentFilter(relation_field_name, copied_origin_ids),
                parent_relation_field=field_link.field,
            )

    def _execute_copy_on_compound_actions(
        self, model_config: ModelCopyConfig, output_map: OutputMap
    ) -> None:
        for compound_config in model_config.compound_copy_actions:
            affected_map = {k: list(v.keys()) for k, v in output_map.items()}
            extra_filters = self._get_extra_filters_for_compound_actions(
                model_config=compound_config, affected_map=affected_map
            )
            if not extra_filters:
                continue
            self.copy_model(
                model_config=compound_config,
                output_map=output_map,
                extra_filters=extra_filters,
            )

    def _execute_copy_intent_list(
        self,
        model_class: type[Model],
        copy_intent_list: list[CopyIntent],
        output_map: OutputMap,
        parent_relation_field: ForeignKey[Any, Any] | None = None,
    ) -> list[Model]:
        copies_to_create: list[Model] = []
        for copy_intent in copy_intent_list:
            model_data = {**copy_intent.copy_data}
            if parent_relation_field:
                relation_field_name = parent_relation_field.attname
                relation_model_name = self._key(parent_relation_field.related_model)
                copied_parent_id = output_map[relation_model_name][
                    str(getattr(copy_intent.origin, relation_field_name))
                ]
                model_data[relation_field_name] = copied_parent_id
            copies_to_create.append(model_class(**model_data))
        if not copies_to_create:
            return []

        try:
            created_copy_list = self._manager(model_class).bulk_create(
                copies_to_create, batch_size=self.batch_size
            )
        except IntegrityError:
            logger.exception("Error on creating %s", model_class._meta.label)
            raise

        if any(created.pk is None for created in created_copy_list):
            db_alias = self._write_db(model_class)
            raise NotSupportedError(
                f"bulk_create() on database '{db_alias}' "
                f"({connections[db_alias].vendor}) did not return primary keys for "
                f"{model_class._meta.label}. django-copyist needs them to link copied "
                f"rows. Use PostgreSQL, SQLite 3.35+ or MariaDB, or give the model "
                f"a primary key with a Python-side default (for example UUIDField(default=uuid4))."
            )

        return created_copy_list

    def copy_model(
        self,
        model_config: ModelCopyConfig,
        output_map: OutputMap,
        extra_filters: Q | None = None,
        parent_relation_field: ForeignKey[Any, Any] | None = None,
        parent_filter: ParentFilter | None = None,
    ) -> OutputMap:
        self.run_data_preparation(model_config, output_map)

        instance_list = self._get_instances_for_model_config(
            model_config=model_config, extra_filters=extra_filters, parent_filter=parent_filter
        )
        ignored_ids = set(self.ignored_map.get(self._key(model_config.model), ()))
        if ignored_ids:
            instance_list = [i for i in instance_list if i.pk not in ignored_ids]
        if not instance_list:
            return output_map
        model_class = model_config.model

        copy_intent_list = [CopyIntent(origin=i) for i in instance_list]
        for field_name, field_copy_config in model_config.field_copy_actions.items():
            self._evaluate_field_values(
                field_name=field_name,
                field_copy_config=field_copy_config,
                output_map=output_map,
                copy_intent_list=copy_intent_list,
                instance_list=instance_list,
                model_class=model_class,
            )

        if not copy_intent_list:
            return output_map

        created_copy_list = self._execute_copy_intent_list(
            model_class=model_class,
            copy_intent_list=copy_intent_list,
            output_map=output_map,
            parent_relation_field=parent_relation_field,
        )

        if self._key(model_class) not in output_map:
            output_map[self._key(model_class)] = {}

        model_output_map = output_map[self._key(model_class)]
        for copy_intent, created_copy in zip(copy_intent_list, created_copy_list):
            model_output_map[str(copy_intent.origin.pk)] = str(created_copy.pk)
            copy_intent.copied = created_copy

        self._create_m2m_relations_for_update_to_copied(
            model_class=model_class,
            copy_intent_list=copy_intent_list,
            output_map=output_map,
        )
        self._execute_copy_for_make_copy_fields(
            model_config=model_config,
            output_map=output_map,
            copy_intent_list=copy_intent_list,
        )
        self._execute_copy_on_compound_actions(model_config=model_config, output_map=output_map)
        self.run_postcopy_steps(
            model_config=model_config,
            output_map=output_map,
            copy_intent_list=copy_intent_list,
        )

        return output_map

    @property
    def _is_missing_values_in_set_to_filter_map(self) -> bool:
        for set_to_filter_group in self.set_to_filter_map.values():
            for model_filter_map in set_to_filter_group.values():
                for value in model_filter_map.values():
                    if value is None:
                        return True
        return False

    def execute_copy(self) -> OutputMap:
        output_map: OutputMap = {}

        for model_config in self.config.model_configs:
            self.copy_model(model_config=model_config, output_map=output_map)
        return output_map

    def _check_should_abort(self) -> CopyResult | None:
        abort_reason = None

        if self._is_missing_values_in_set_to_filter_map:
            if not self.request.confirm_write:
                abort_reason = AbortReason.NOT_MATCHED
            elif (
                self.request.set_to_filter_map is not None
                and self.request.set_to_filter_map != self.set_to_filter_map
            ):
                abort_reason = AbortReason.DATA_CHANGED_STF
        if self.ignored_map:
            if not self.request.confirm_write:
                abort_reason = AbortReason.IGNORED
            elif (
                self.request.ignored_map is not None
                and self.request.ignored_map != self.ignored_map
            ):
                abort_reason = AbortReason.DATA_CHANGED_IGNORED

        if not abort_reason:
            return None

        return CopyResult(
            reason=abort_reason,
            is_copy_successful=False,
            set_to_filter_map=self.set_to_filter_map,
            ignored_map=self.ignored_map,
            output_map=None,
            map_keys=self.config.map_keys,
            model_labels=self._model_labels(),
        )

    def execute_copy_request(self) -> CopyResult:
        self.validate_config()
        abort_result = self._check_should_abort()
        if abort_result:
            return abort_result

        with transaction.atomic(using=self._write_db(self.config.model_configs[0].model)):
            output_map = self.execute_copy()

        return CopyResult(
            is_copy_successful=True,
            set_to_filter_map=self.set_to_filter_map,
            ignored_map=self.ignored_map,
            output_map=output_map,
            map_keys=self.config.map_keys,
            model_labels=self._model_labels(),
        )

    def _model_labels(self) -> dict[str, str]:
        return map_key_labels(self.config.model_configs, self.config.map_keys)
