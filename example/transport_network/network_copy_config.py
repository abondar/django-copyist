from typing import TYPE_CHECKING, Any

from django.db.models import Model, Q

from django_copyist.config import (
    TAKE_FROM_ORIGIN,
    CopyActions,
    DataModificationActions,
    DataPreparationStep,
    FieldCopyConfig,
    FieldFilterConfig,
    FilterConfig,
    FilterSource,
    IgnoreCondition,
    IgnoreFilter,
    IgnoreFilterSource,
    ModelCopyConfig,
)
from example.transport_network.models import (
    Edge,
    Forecast,
    Node,
    Project,
    Route,
    RouteAttribute,
    RouteDirection,
    RouteDirectionEdge,
    RouteDirectionEdgeOrder,
    RouteDirectionNode,
    RouteVariant,
    RouteVehicleCount,
    Scenario,
    Stop,
)

if TYPE_CHECKING:
    from django_copyist.copyist import FieldSetToFilterMap, OutputMap, SetToFilterMap


def delete_forecasts(
    model_config: ModelCopyConfig,
    input_data: dict[str, Any],
    set_to_filter_map: "SetToFilterMap",
    output_map: "OutputMap",
) -> None:
    project = Project.objects.get(scenarios=input_data["target_scenario_id"])

    Forecast.objects.filter(shape__project=project).delete()


def find_matching_stops_by_nodes(
    model_config: "ModelCopyConfig",
    input_data: dict[str, Any],
    field_name: str,
    field_copy_config: "FieldCopyConfig",
    set_to_filter_map: "SetToFilterMap",
    instance_list: list[Model],
    referenced_instance_list: list[Model],
) -> "FieldSetToFilterMap":
    stop_id_list = [s.id for s in referenced_instance_list]

    stops_with_nodes = list(
        Stop.objects.filter(id__in=stop_id_list).select_related("node")
    )

    point_list = [s.node.point for s in stops_with_nodes]
    substitute_stops = Stop.objects.filter(
        node__point__in=point_list,
        node__scenario_id=input_data["target_scenario_id"],
    ).select_related("node")
    point_substitute_map = {s.node.point: s.pk for s in substitute_stops}

    field_set_to_filter_map = {}
    for stop in stops_with_nodes:
        point = stop.node.point
        field_set_to_filter_map[str(stop.id)] = point_substitute_map.get(point)
    return field_set_to_filter_map


def find_matching_edges(
    model_config: "ModelCopyConfig",
    input_data: dict[str, Any],
    field_name: str,
    field_copy_config: "FieldCopyConfig",
    set_to_filter_map: "SetToFilterMap",
    instance_list: list[Model],
    referenced_instance_list: list[Model],
) -> "FieldSetToFilterMap":
    original_edge_id_list = [i.pk for i in referenced_instance_list]
    referenced_instance_list_with_prefetched = Edge.objects.filter(
        id__in=original_edge_id_list
    ).select_related(
        "first_node",
        "last_node",
    )
    position_filter = Q()
    edge_to_point_map: dict[int, tuple[str, str]] = {}

    for edge in referenced_instance_list_with_prefetched:
        position_filter |= Q(first_node__point=edge.first_node.point) & (
            Q(last_node__point=edge.last_node.point)
        )
        edge_to_point_map[edge.id] = (edge.first_node.point, edge.last_node.point)

    substitute_list = (
        Edge.objects.filter(position_filter)
        .filter(
            scenario_id=input_data["target_scenario_id"],
        )
        .select_related(
            "first_node",
            "last_node",
        )
        .prefetch_related("vehicle_types")
    )
    point_to_substitute_list: dict[tuple[str, str], int] = {}
    substitute_map: dict[int, Edge] = {}
    for edge in substitute_list:
        point_to_substitute_list[(edge.first_node.point, edge.last_node.point)] = (
            edge.id
        )
        substitute_map[edge.id] = edge

    field_set_to_filter_map = {}
    for edge in referenced_instance_list:
        edge_points = edge_to_point_map[edge.id]
        substitute_id = point_to_substitute_list.get(edge_points)
        if not substitute_id:
            field_set_to_filter_map[str(edge.pk)] = None
            continue

        substitute = substitute_map[substitute_id]
        field_set_to_filter_map[str(edge.pk)] = str(substitute.pk)
    return field_set_to_filter_map


ROUTE_VARIANT_COPY_CONFIG = ModelCopyConfig(
    model=RouteVariant,
    field_copy_actions={
        "tariff": TAKE_FROM_ORIGIN,
        "tariff_id": TAKE_FROM_ORIGIN,
        "variant_name": TAKE_FROM_ORIGIN,
        "variant_number": TAKE_FROM_ORIGIN,
        "directions": FieldCopyConfig(
            action=CopyActions.MAKE_COPY,
            copy_with_config=ModelCopyConfig(
                model=RouteDirection,
                ignore_condition=IgnoreCondition(
                    filter_conditions=[
                        IgnoreFilter(
                            filter_name="path_nodes__node__in",
                            filter_source=IgnoreFilterSource.UNMATCHED_SET_TO_FILTER_VALUES,
                            set_to_filter_origin_model=RouteDirectionNode,
                            set_to_filter_field_name="node",
                        ),
                        IgnoreFilter(
                            filter_name="path_nodes__stop__in",
                            filter_source=IgnoreFilterSource.UNMATCHED_SET_TO_FILTER_VALUES,
                            set_to_filter_origin_model=RouteDirectionNode,
                            set_to_filter_field_name="stop",
                        ),
                        IgnoreFilter(
                            filter_name=(
                                "path_nodes__path_out__route_direction_edge_order__edge__in"
                            ),
                            filter_source=IgnoreFilterSource.UNMATCHED_SET_TO_FILTER_VALUES,
                            set_to_filter_origin_model=RouteDirectionEdgeOrder,
                            set_to_filter_field_name="edge",
                        ),
                        IgnoreFilter(
                            filter_name="path_nodes__path_in__route_direction_edge_order__edge__in",
                            filter_source=IgnoreFilterSource.UNMATCHED_SET_TO_FILTER_VALUES,
                            set_to_filter_origin_model=RouteDirectionEdgeOrder,
                            set_to_filter_field_name="edge",
                        ),
                    ]
                ),
                field_copy_actions={
                    "direction": TAKE_FROM_ORIGIN,
                    "length": TAKE_FROM_ORIGIN,
                    "direction_name": TAKE_FROM_ORIGIN,
                    "number_of_trips": TAKE_FROM_ORIGIN,
                    "path_nodes": FieldCopyConfig(
                        action=CopyActions.MAKE_COPY,
                        copy_with_config=ModelCopyConfig(
                            model=RouteDirectionNode,
                            field_copy_actions={
                                "order": TAKE_FROM_ORIGIN,
                                "stop": FieldCopyConfig(
                                    action=CopyActions.SET_TO_FILTER,
                                    filter_config=FilterConfig(
                                        filter_func=find_matching_stops_by_nodes
                                    ),
                                    reference_to=Stop,
                                ),
                                "node": FieldCopyConfig(
                                    action=CopyActions.SET_TO_FILTER,
                                    reference_to=Node,
                                    filter_config=FilterConfig(
                                        filters={
                                            "scenario_id": FieldFilterConfig(
                                                source=FilterSource.FROM_INPUT,
                                                key="target_scenario_id",
                                            ),
                                            "point": FieldFilterConfig(
                                                source=FilterSource.FROM_ORIGIN
                                            ),
                                        }
                                    ),
                                ),
                            },
                        ),
                    ),
                },
            ),
        ),
    },
)


ROUTE_NETWORK_COPY_CONFIG = ModelCopyConfig(
    model=Route,
    filter_field_to_input_key={
        "scenario_id": "origin_scenario_id",
    },
    data_preparation_steps=[
        DataPreparationStep(
            action=DataModificationActions.EXECUTE_FUNC, func=delete_forecasts
        ),
        DataPreparationStep(
            action=DataModificationActions.DELETE_BY_FILTER,
            filter_field_to_input_key={
                "scenario_id": "target_scenario_id",
            },
        ),
    ],
    field_copy_actions={
        "source_route_id": TAKE_FROM_ORIGIN,
        "route_number": TAKE_FROM_ORIGIN,
        "vehicle_type": TAKE_FROM_ORIGIN,
        "route_long_name": TAKE_FROM_ORIGIN,
        "is_circle": TAKE_FROM_ORIGIN,
        "carrier": TAKE_FROM_ORIGIN,
        "communication_type": TAKE_FROM_ORIGIN,
        "season": TAKE_FROM_ORIGIN,
        "regular_transportation_type": TAKE_FROM_ORIGIN,
        "scenario": FieldCopyConfig(
            action=CopyActions.SET_TO_FILTER,
            reference_to=Scenario,
            filter_config=FilterConfig(
                filters={
                    "id": FieldFilterConfig(
                        source=FilterSource.FROM_INPUT, key="target_scenario_id"
                    )
                }
            ),
        ),
        "vehicle_count": FieldCopyConfig(
            action=CopyActions.MAKE_COPY,
            copy_with_config=ModelCopyConfig(
                model=RouteVehicleCount,
                field_copy_actions={
                    "vehicle_class": TAKE_FROM_ORIGIN,
                    "count": TAKE_FROM_ORIGIN,
                },
            ),
        ),
        "variants": FieldCopyConfig(
            action=CopyActions.MAKE_COPY,
            copy_with_config=ROUTE_VARIANT_COPY_CONFIG,
        ),
    },
    compound_copy_actions=[
        ModelCopyConfig(
            model=RouteAttribute,
            field_copy_actions={
                "vehicle_type": TAKE_FROM_ORIGIN,
                "attribute_id": TAKE_FROM_ORIGIN,
                "name": TAKE_FROM_ORIGIN,
                "value": TAKE_FROM_ORIGIN,
                "routes": FieldCopyConfig(
                    action=CopyActions.UPDATE_TO_COPIED,
                    reference_to=Route,
                ),
            },
        ),
        ModelCopyConfig(
            model=RouteDirectionEdge,
            field_copy_actions={
                "direction_node_from": FieldCopyConfig(
                    action=CopyActions.UPDATE_TO_COPIED,
                    reference_to=RouteDirectionNode,
                ),
                "direction_node_to": FieldCopyConfig(
                    action=CopyActions.UPDATE_TO_COPIED,
                    reference_to=RouteDirectionNode,
                ),
                "route_direction_edge_order": FieldCopyConfig(
                    action=CopyActions.MAKE_COPY,
                    copy_with_config=ModelCopyConfig(
                        model=RouteDirectionEdgeOrder,
                        field_copy_actions={
                            "order": TAKE_FROM_ORIGIN,
                            "edge": FieldCopyConfig(
                                action=CopyActions.SET_TO_FILTER,
                                reference_to=Edge,
                                filter_config=FilterConfig(
                                    filter_func=find_matching_edges,
                                ),
                            ),
                        },
                    ),
                ),
            },
        ),
    ],
)
