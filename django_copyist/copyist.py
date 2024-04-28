import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from django.db import IntegrityError, transaction
from django.db.models import ForeignKey, Model, Q
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
    FilterSource,
    IgnoreFilterSource,
    ModelCopyConfig,
    get_queryset_for_model_config,
)
from django_copyist.copy_request import AbortReason, CopyRequest, CopyResult

logger = logging.getLogger(__name__)

FieldSetToFilterMap = dict[str, Optional[str]]
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

    def __post_init__(self):
        for key in (self.backward_id_key, self.forward_id_key):
            if getattr(self.through_model, key, None) is None:
                raise ValueError(
                    f"Not found key {key} on through model {self.through_model.__name__}"
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

    def __repr__(self):
        return (
            f"CopyIntent: {self.origin.__class__.__name__}\n"
            f"Copied: {bool(self.copied)}\n"
            f"m2m: {self.m2m_copy_intent_list}"
        )


@dataclass
class CopyistConfig:
    """
    Root copy config, containing ModelCopyConfig list
    """

    model_configs: list[ModelCopyConfig]


@dataclass
class IgnoreEvaluation:
    """
    Intermediate model storing intent after validation to resolve ignore conditions
    """

    model_config: ModelCopyConfig
    original_extra_filter: Q | None


class Copyist:
    def __init__(self, copy_request: CopyRequest):
        self.request = copy_request
        self.config = copy_request.config
        self.input_data = copy_request.input_data

        self._set_to_filter_map: SetToFilterMap | None = None
        self._validation_affected_map: ValidationAffectedMap | None = None
        self._ignored_map: IgnoredMap | None = None
        self._ignore_conditions_to_resolve: list[IgnoreEvaluation] | None = None

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
    def ignored_map(self) -> IgnoredMap:
        if self._ignored_map is None:
            raise AttributeError("ignored_map referenced before validation")
        return self._ignored_map

    @classmethod
    def get_copyist_for_request(cls, request: CopyRequest) -> "Copyist":
        return cls(config=cls.CONFIGS_MAP[request.type], input_data=request.input_data)

    def _get_instances_for_model_config(
        self, model_config: ModelCopyConfig, extra_filters: Q | None
    ) -> list[Model]:
        return list(
            get_queryset_for_model_config(
                model_config=model_config,
                extra_filters=extra_filters,
                input_data=self.input_data,
            )
        )

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
                f"Field {field_name} was declared in {model_config.model.__name__} "
                f"config, but not present on model"
            )
        if not isinstance(
            field_link, (ForwardManyToOneDescriptor, ManyToManyDescriptor)
        ):
            raise ValueError(
                f"Expected ForeignKeyField or ManyToManyField field on {field_name} for "
                f"SET_TO_FILTER config, but got {field_link.__class__.__name__}"
            )

        if isinstance(field_link, ManyToManyDescriptor):
            if field_link.reverse:
                relation_key = field_link.field.name
            else:
                relation_key = field_link.field.related_query_name()
            filter_key = f"{relation_key}__id"

            instance_id_list = [i.pk for i in instance_list]
            field_copy_config.reference_to.objects.filter(
                **{f"{filter_key}__in": instance_id_list}
            )
            referenced_instance_list = list(
                field_copy_config.reference_to.objects.filter(
                    **{f"{filter_key}__in": instance_id_list}
                )
            )
            return referenced_instance_list
        elif isinstance(field_link, ForwardManyToOneDescriptor):
            id_key_field_name = f"{field_name}_id"
            referenced_id_values = [
                getattr(instance, id_key_field_name) for instance in instance_list
            ]

            referenced_model = field_copy_config.reference_to
            referenced_instance_list = list(
                referenced_model.objects.filter(id__in=referenced_id_values)
            )
            return referenced_instance_list
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
        referenced_model = field_copy_config.reference_to
        substitutes_query = referenced_model.objects.all()
        for (
            filter_field_name,
            filter_config,
        ) in field_copy_config.filter_config.filters.items():
            if filter_config.source == FilterSource.FROM_INPUT:
                filter_value = self.input_data.get(filter_config.key)
                if not filter_value:
                    raise ValueError(
                        f"Filter {filter_field_name} was declared, "
                        f"but value for {filter_config.key} not found in input_data"
                    )
                substitutes_query = substitutes_query.filter(
                    **{filter_field_name: filter_value}
                )
            elif filter_config.source == FilterSource.FROM_ORIGIN:
                shared_values = [
                    getattr(i, filter_field_name) for i in referenced_instance_list
                ]
                substitutes_query = substitutes_query.filter(
                    **{f"{filter_field_name}__in": shared_values}
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
            for k, v in field_copy_config.filter_config.filters.items()
            if v.source == FilterSource.FROM_ORIGIN
        }
        for referenced_instance in referenced_instance_list:
            substitute_conditions = []
            for filter_field_name in take_from_origin_filters.keys():
                substitute_conditions.append(
                    SubstituteCondition(
                        filter_field_name=filter_field_name,
                        filter_field_value=getattr(
                            referenced_instance, filter_field_name
                        ),
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
                field_set_to_filter_map[str(referenced_instance.pk)] = str(
                    substitute_instance.pk
                )
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
    ):
        referenced_instance_list = self._get_referenced_instance_list(
            model_config=model_config,
            field_name=field_name,
            field_copy_config=field_copy_config,
            instance_list=instance_list,
        )
        if field_copy_config.filter_config.filters:
            field_set_to_filter_map = self._get_field_set_to_filter_map_for_filters(
                field_copy_config=field_copy_config,
                referenced_instance_list=referenced_instance_list,
            )
        elif field_copy_config.filter_config.filter_func:
            field_set_to_filter_map = field_copy_config.filter_config.filter_func(
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

        if model_config.model.__name__ not in set_to_filter_map:
            set_to_filter_map[model_config.model.__name__] = {}
        set_to_filter_map[model_config.model.__name__][
            field_name
        ] = field_set_to_filter_map

    def _execute_make_copy_config_validation(
        self,
        model_config: ModelCopyConfig,
        field_copy_config: FieldCopyConfig,
        field_name: str,
        set_to_filter_map: dict,
        instance_list: list[Model],
    ):
        instance_id_list = [i.pk for i in instance_list]
        field_link = getattr(model_config.model, field_name, None)
        if not field_link:
            raise ValueError(
                f"Field {field_name} was declared in {model_config.model.__name__} "
                f"config, but not present on model"
            )

        if not isinstance(field_link, ReverseManyToOneDescriptor):
            raise ValueError(
                f"Expected Many to One field on {field_name} for "
                f"MAKE_COPY config, but got {field_link.__class__.__name__}"
            )

        relation_field_name = field_link.field.attname

        self._run_validation_for_model(
            model_config=field_copy_config.copy_with_config,
            set_to_filter_map=set_to_filter_map,
            model_extra_filters=Q(**{f"{relation_field_name}__in": instance_id_list}),
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

            if field_copy_config.reference_to == model_config.model:
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
                    f"{model_config.model.__name__}, got {field_link.__class__.__name__}"
                )

        for field_name in fk_fields_to_filter:
            field_copy_config = model_config.field_copy_actions[field_name]
            copied_referenced_id_list = affected_map.get(
                field_copy_config.reference_to.__name__
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
                    field_copy_config.reference_to.__name__
                )
                if not copied_referenced_id_list:
                    continue

                extra_filters &= Q(
                    **{f"{field_name}__in": copied_referenced_id_list}
                ) | Q(**{field_name: None})
        else:
            result_nullable_filter = Q()
            for field_name in nullable_fields_to_filter:
                field_copy_config = model_config.field_copy_actions[field_name]
                copied_referenced_id_list = affected_map.get(
                    field_copy_config.reference_to.__name__
                )
                if not copied_referenced_id_list:
                    continue
                combination_filter = Q(
                    **{f"{field_name}__in": copied_referenced_id_list}
                )
                for other_field in [
                    f for f in nullable_fields_to_filter if f != field_name
                ]:
                    other_field_copy_config = model_config.field_copy_actions[
                        field_name
                    ]
                    copied_other_referenced_id_list = affected_map.get(
                        other_field_copy_config.reference_to.__name__
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
    ) -> list[Model]:
        ignore_filter = Q()
        for condition in model_config.ignore_condition.filter_conditions:
            if (
                condition.filter_source
                == IgnoreFilterSource.UNMATCHED_SET_TO_FILTER_VALUES
            ):
                value_model_map = set_to_filter_map[
                    condition.set_to_filter_origin_model.__name__
                ].get(condition.set_to_filter_field_name)
                if not value_model_map:
                    continue
                unmatched_id_list = [k for k, v in value_model_map.items() if v is None]
                if not unmatched_id_list:
                    continue
                ignore_filter |= Q(**{condition.filter_name: unmatched_id_list})

        if not ignore_filter:
            return []

        if model_extra_filter:
            ignore_filter &= model_extra_filter

        ignored_values = self._get_instances_for_model_config(
            model_config, extra_filters=ignore_filter
        )
        return ignored_values

    def _evaluate_ignored(
        self,
        model_config: ModelCopyConfig,
        set_to_filter_map: SetToFilterMap,
        model_extra_filter: Q | None,
    ):
        if not model_config.ignore_condition:
            return

        if model_config.ignore_condition.filter_conditions:
            ignored_values = self._evaluate_ignored_by_filters(
                model_config=model_config,
                set_to_filter_map=set_to_filter_map,
                model_extra_filter=model_extra_filter,
            )
        elif model_config.ignore_condition.ignore_func:
            ignored_values = model_config.ignore_condition.ignore_func(
                model_config=model_config,
                set_to_filter_map=set_to_filter_map,
                model_extra_filter=model_extra_filter,
                ignored_map=self._ignored_map,
                input_data=self.input_data,
            )
        else:
            raise ValueError("No ignore func or filter condition on ignore condition")

        if not ignored_values:
            return
        self._ignored_map[model_config.model.__name__] = list(
            {i.pk for i in ignored_values}
        )

    def _run_validation_for_model(
        self,
        model_config: ModelCopyConfig,
        set_to_filter_map: SetToFilterMap,
        model_extra_filters: Q | None = None,
    ) -> SetToFilterMap:
        instance_list = self._get_instances_for_model_config(
            model_config, extra_filters=model_extra_filters
        )
        if model_config.model.__name__ in self._validation_affected_map:
            raise ValueError(
                f"Model {model_config.model.__name__} has been configured for copy several times"
            )
        self._validation_affected_map[model_config.model.__name__] = [
            i.pk for i in instance_list
        ]

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
                model_config=compound_config, affected_map=self._validation_affected_map
            )
            if not extra_filters:
                continue
            self._run_validation_for_model(
                model_config=compound_config,
                set_to_filter_map=set_to_filter_map,
                model_extra_filters=extra_filters,
            )

        if model_config.ignore_condition:
            self._ignore_conditions_to_resolve.append(
                IgnoreEvaluation(
                    model_config=model_config, original_extra_filter=model_extra_filters
                )
            )

        return set_to_filter_map

    def _resolve_ignore_conditions(self, set_to_filter_map: SetToFilterMap):
        for condition in self._ignore_conditions_to_resolve:
            self._evaluate_ignored(
                model_config=condition.model_config,
                set_to_filter_map=set_to_filter_map,
                model_extra_filter=condition.original_extra_filter,
            )

    def validate_config(self):
        set_to_filter_map: SetToFilterMap = {}
        self._validation_affected_map = {}
        self._ignored_map = {}
        self._ignore_conditions_to_resolve = []

        for model_config in self.config.model_configs:
            if not model_config.filter_field_to_input_key:
                raise ValueError(
                    f"Root config must describe filter_filed_to_input_key map, "
                    f"to narrow the query on {model_config.model.__name__}"
                )
            self._run_validation_for_model(
                model_config=model_config,
                set_to_filter_map=set_to_filter_map,
            )
        self._resolve_ignore_conditions(set_to_filter_map)
        self._set_to_filter_map = set_to_filter_map

    def _evaluate_take_from_origin_field_values(
        self,
        model_class: type[Model],
        field_name: str,
        copy_intent_list: list[CopyIntent],
    ) -> None:
        for copy_intent in copy_intent_list:
            class_field = getattr(copy_intent.origin.__class__, field_name, None)
            if isinstance(class_field, ManyToManyDescriptor):
                referenced_model = (
                    class_field.field.model
                    if class_field.reverse
                    else class_field.field.related_model
                )

                self._evaluate_m2m_field_values(
                    field_name=field_name,
                    field_link=getattr(copy_intent.origin.__class__, field_name),
                    instance_id_list=[c.origin.pk for c in copy_intent_list],
                    copy_intent_list=copy_intent_list,
                    referenced_model=referenced_model,
                    use_copied_related_instances=False,
                )
                continue

            try:
                origin_value = getattr(copy_intent.origin, field_name)
            except AttributeError as e:
                raise ValueError(
                    f"{field_name} declared for copy from origin, "
                    f"but field not found on model {model_class.__name__}"
                ) from e

            copy_intent.copy_data[field_name] = origin_value

    def _evaluate_take_from_input_field_values(
        self, field_name: str, copy_intent_list: list[CopyIntent], input_key: str
    ) -> None:
        for copy_intent in copy_intent_list:
            input_value = self.input_data.get(input_key)
            if input_value is None:
                raise ValueError(f"No {input_key} in input_data")
            copy_intent.copy_data[field_name] = input_value

    def _get_m2m_relation_map(
        self,
        field_link: ManyToManyDescriptor,
        instance_id_list: list[Any],
        backward_filter_key: str,
        m2m_backward_id_field_name: str,
        m2m_forward_id_field_name: str,
    ) -> dict[str, list[str]]:
        through_model = field_link.through
        through_records = list(
            through_model.objects.filter(**{backward_filter_key: instance_id_list})
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
        update_origin_id_from_set_to_filter: bool,
        use_set_to_filter_values: bool,
    ):
        for copy_intent in copy_intent_list[:]:
            ids_linked_to_origin = m2m_map.get(str(copy_intent.origin.pk))
            if ids_linked_to_origin:
                if update_origin_id_from_set_to_filter:
                    updated_id_list = []
                    model_set_to_filter_map = self.set_to_filter_map[
                        copy_intent.origin.__class__.__name__
                    ][field_name]
                    for related_id in ids_linked_to_origin:
                        updated_id_list.append(model_set_to_filter_map.get(related_id))

                    if None in updated_id_list:
                        copy_intent_list.remove(copy_intent)
                        continue

                    related_id_list = updated_id_list
                else:
                    related_id_list = ids_linked_to_origin

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
        field_link: ManyToManyDescriptor,
        instance_id_list: list[Any],
        copy_intent_list: list[CopyIntent],
        referenced_model: type[Model],
        use_copied_related_instances: bool = False,
        use_set_to_filter_values: bool = False,
        update_origin_id_from_set_to_filter: bool = False,
    ):
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
            update_origin_id_from_set_to_filter=update_origin_id_from_set_to_filter,
            use_set_to_filter_values=use_set_to_filter_values,
        )

    def _evaluate_reverse_fk_field_values(
        self,
        field_link: ForwardManyToOneDescriptor,
        model_output_map: dict[str, str],
        copy_intent_list: list[CopyIntent],
        referenced_model: type[Model],
    ):
        id_field_name = field_link.field.attname
        for copy_intent in copy_intent_list:
            referenced_instance_id = getattr(copy_intent.origin, id_field_name)
            if referenced_instance_id is None:
                copy_id = None
            else:
                copy_id = model_output_map.get(str(referenced_instance_id))
                if not copy_id:
                    raise ValueError(
                        f"Copy of {referenced_model.__name__} with id {referenced_instance_id} "
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
    ):
        referenced_model = field_copy_config.reference_to

        field_link = getattr(model_class, field_name)
        if not isinstance(
            field_link, (ForwardManyToOneDescriptor, ManyToManyDescriptor)
        ):
            raise ValueError(
                f"Expected ManyToOne or ManyToMany field on {field_name} for "
                f"UPDATE_TO_COPIED config, but got "
                f"{field_link.__class__.__name__}, on {model_class.__name__}"
            )

        if isinstance(field_link, ManyToManyDescriptor) and field_link.reverse:
            real_referenced_model = field_link.field.model
        else:
            real_referenced_model = field_link.field.related_model

        if real_referenced_model != referenced_model:
            raise ValueError(
                f'"{referenced_model.__name__}" was referenced from '
                f'{model_class.__name__} by field "{field_name}", '
                f'but "{real_referenced_model.__name__}" was found by that name'
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
    ):
        field_link = getattr(model_class, field_name)
        id_field_name = field_link.field.attname
        referenced_model = field_copy_config.reference_to
        model_set_to_filter_map = self.set_to_filter_map[model_class.__name__].get(
            field_name
        )

        for copy_intent in copy_intent_list[:]:
            if isinstance(field_link, ManyToManyDescriptor):
                self._evaluate_m2m_field_values(
                    field_name=field_name,
                    field_link=getattr(copy_intent.origin.__class__, field_name),
                    instance_id_list=[c.origin.pk for c in copy_intent_list],
                    copy_intent_list=copy_intent_list,
                    referenced_model=referenced_model,
                    use_set_to_filter_values=True,
                )
                continue

            origin_related_id = getattr(copy_intent.origin, id_field_name)
            if origin_related_id is None:
                substitute_id = None
            else:
                if not model_set_to_filter_map:
                    raise RuntimeError(
                        f"No model filters are ready for "
                        f"{referenced_model.__name__} in {field_name}"
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
    ):
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
                field_name=field_name,
                copy_intent_list=copy_intent_list,
                input_key=field_copy_config.input_key,
            )
        elif field_copy_config.action == CopyActions.UPDATE_TO_COPIED:
            referenced_model = field_copy_config.reference_to
            model_output_map = output_map.get(referenced_model.__name__, {})

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
    ):
        filters = {}
        for filter_field, input_key in step.filter_field_to_input_key.items():
            value = self.input_data[input_key]
            filters[filter_field] = value
        model_config.model.objects.filter(**filters).delete()

    def run_data_preparation(
        self, model_config: ModelCopyConfig, output_map: OutputMap
    ):
        for step in model_config.data_preparation_steps:
            if step.action == DataModificationActions.DELETE_BY_FILTER:
                self._execute_delete_by_filter_step(model_config, step)
            elif step.action == DataModificationActions.EXECUTE_FUNC:
                step.func(
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
    ):
        for step in model_config.postcopy_steps:
            if step.action == DataModificationActions.DELETE_BY_FILTER:
                self._execute_delete_by_filter_step(model_config, step)
            elif step.action == DataModificationActions.EXECUTE_FUNC:
                step.func(
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
            related_output_map = output_map.get(m2m_copy_intent.to_model.__name__)
            if not related_output_map:
                raise ValueError(
                    f"{model_class.__name__} referenced before any copies were made"
                )
            copied_related_id = related_output_map.get(related_id)
            if not copied_related_id:
                raise ValueError(
                    f"Copy of {model_class.__name__} with {related_id} "
                    f"was not found in output map"
                )
            copied_related_id_list.append(copied_related_id)
        return copied_related_id_list

    def _create_m2m_relations_for_update_to_copied(
        self,
        model_class: type[Model],
        copy_intent_list: list[CopyIntent],
        output_map: OutputMap,
    ):
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
                        m2m_copy_intent.from_model.__name__
                    ][m2m_copy_intent.field_name]
                    related_id_list_to_create = [
                        field_set_to_filter_map[related_id]
                        for related_id in m2m_copy_intent.related_id_list
                        if field_set_to_filter_map.get(related_id)
                    ]
                else:
                    related_id_list_to_create = m2m_copy_intent.related_id_list

                m2m_relations_to_create[m2m_copy_intent.through_model] += [
                    m2m_copy_intent.through_model(
                        **{
                            m2m_copy_intent.backward_id_key: copy_intent.copied.pk,
                            m2m_copy_intent.forward_id_key: related_id,
                        }
                    )
                    for related_id in related_id_list_to_create
                ]

        for model, to_create in m2m_relations_to_create.items():
            model.objects.bulk_create(to_create)

    def _execute_copy_for_make_copy_fields(
        self,
        model_config: ModelCopyConfig,
        instance_list: list[Model],
        output_map: OutputMap,
    ):
        for field_name, field_copy_config in model_config.field_copy_actions.items():
            if field_copy_config.action != CopyActions.MAKE_COPY:
                continue

            instance_id_list = [i.pk for i in instance_list]
            field_link = getattr(model_config.model, field_name)

            relation_field_name = field_link.field.attname
            self.copy_model(
                model_config=field_copy_config.copy_with_config,
                output_map=output_map,
                extra_filters=Q(**{f"{relation_field_name}__in": instance_id_list}),
                parent_relation_field=field_link.field,
            )

    def _execute_copy_on_compound_actions(
        self, model_config: ModelCopyConfig, output_map: OutputMap
    ):
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
        parent_relation_field: ForeignKey | None = None,
    ) -> list[Model]:
        copies_to_create: list[Model] = []
        for copy_intent in copy_intent_list:
            model_data = {**copy_intent.copy_data}
            if parent_relation_field:
                relation_field_name = parent_relation_field.attname
                relation_model_name = parent_relation_field.related_model.__name__
                copied_parent_id = output_map[relation_model_name][
                    str(getattr(copy_intent.origin, relation_field_name))
                ]
                model_data[relation_field_name] = copied_parent_id
            copies_to_create.append(model_class(**model_data))
        if not copies_to_create:
            return []

        try:
            created_copy_list = model_class.objects.bulk_create(copies_to_create)
        except IntegrityError:
            logger.exception("Error on creating %s", model_class.__name__)
            raise

        return created_copy_list

    def _apply_ignored_to_extra_filters(
        self, model_class: type[Model], extra_filters: Q | None
    ) -> Q | None:
        if model_class.__name__ not in self._ignored_map:
            return extra_filters

        ignored_id_list = self._ignored_map[model_class.__name__]
        result_filter = ~Q(id__in=ignored_id_list)
        if extra_filters:
            result_filter &= extra_filters
        return result_filter

    def copy_model(
        self,
        model_config: ModelCopyConfig,
        output_map: OutputMap,
        extra_filters: Q | None = None,
        parent_relation_field: ForeignKey | None = None,
    ) -> OutputMap:
        self.run_data_preparation(model_config, output_map)

        filters = self._apply_ignored_to_extra_filters(
            model_config.model, extra_filters
        )
        instance_list = self._get_instances_for_model_config(
            model_config=model_config, extra_filters=filters
        )
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

        if model_class.__name__ not in output_map:
            output_map[model_class.__name__] = {}

        model_output_map = output_map[model_class.__name__]
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
            instance_list=instance_list,
        )
        self._execute_copy_on_compound_actions(
            model_config=model_config, output_map=output_map
        )
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
        output_map = {}

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
        )

    def execute_copy_request(self) -> CopyResult:
        self.validate_config()
        abort_result = self._check_should_abort()
        if abort_result:
            return abort_result

        with transaction.atomic():
            output_map = self.execute_copy()

        return CopyResult(
            is_copy_successful=True,
            set_to_filter_map=self.set_to_filter_map,
            ignored_map=self.ignored_map,
            output_map=output_map,
        )
