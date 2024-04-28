from typing import TYPE_CHECKING, Any, List

from django.db.models import Q

from django_copyist.config import (
    TAKE_FROM_ORIGIN,
    DataModificationActions,
    MakeCopy,
    ModelCopyConfig,
    PostcopyStep,
    UpdateToCopied,
)
from example.transport_network.models import (
    BehaviorCategoryValue,
    BehaviorType,
    Category,
    Edge,
    EdgeVehicleSpeed,
    Indicator,
    IndicatorString,
    Interval,
    Municipality,
    Node,
    Project,
    ProjectFile,
    Region,
    RegionTraffic,
    RegionType,
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
    VehicleClass,
    VehicleType,
)

if TYPE_CHECKING:
    from django_copyist.copyist import CopyIntent, OutputMap, SetToFilterMap


BEHAVIOR_TYPE_MODEL_COPY_CONFIG = ModelCopyConfig(
    model=BehaviorType,
    field_copy_actions={
        "name": TAKE_FROM_ORIGIN,
        "behavior_id": TAKE_FROM_ORIGIN,
        "apply_remote_percent": TAKE_FROM_ORIGIN,
        "category_values": MakeCopy(
            ModelCopyConfig(
                model=BehaviorCategoryValue,
                field_copy_actions={
                    "category": UpdateToCopied(Category),
                    "value": TAKE_FROM_ORIGIN,
                },
            ),
        ),
    },
)

VEHICLE_TYPE_MODEL_COPY_CONFIG = ModelCopyConfig(
    model=VehicleType,
    field_copy_actions={
        "name": TAKE_FROM_ORIGIN,
        "transport_type_id": TAKE_FROM_ORIGIN,
        "max_speed": TAKE_FROM_ORIGIN,
        "is_public": TAKE_FROM_ORIGIN,
        "is_editable": TAKE_FROM_ORIGIN,
        "classes": MakeCopy(
            ModelCopyConfig(
                model=VehicleClass,
                field_copy_actions={
                    "project": UpdateToCopied(Project),
                    "name": TAKE_FROM_ORIGIN,
                    "sits": TAKE_FROM_ORIGIN,
                    "area": TAKE_FROM_ORIGIN,
                    "capacity": TAKE_FROM_ORIGIN,
                },
            ),
        ),
        "route_attributes": MakeCopy(
            ModelCopyConfig(
                model=RouteAttribute,
                field_copy_actions={
                    "attribute_id": TAKE_FROM_ORIGIN,
                    "name": TAKE_FROM_ORIGIN,
                    "value": TAKE_FROM_ORIGIN,
                },
            ),
        ),
    },
)

MUNICIPALITIES_MODEL_COPY_CONFIG = ModelCopyConfig(
    model=Municipality,
    field_copy_actions={
        "name": TAKE_FROM_ORIGIN,
        "regions": MakeCopy(
            ModelCopyConfig(
                model=Region,
                field_copy_actions={
                    "project": UpdateToCopied(Project),
                    "name": TAKE_FROM_ORIGIN,
                    "source_dist_id": TAKE_FROM_ORIGIN,
                    "region_type": TAKE_FROM_ORIGIN,
                },
            ),
        ),
    },
)


def set_base_region_traffic(
    model_config: "ModelCopyConfig",
    input_data: dict[str, Any],
    set_to_filter_map: "SetToFilterMap",
    output_map: "OutputMap",
    copy_intent_list: "List[CopyIntent]",
) -> None:
    base_traffic_to_key = {}
    for copy_intent in copy_intent_list:
        if copy_intent.copied.scenario.is_base:
            traffic = copy_intent.copied
            traffic_key = f"{traffic.region_from_id}__{traffic.region_to_id}__{traffic.interval_id}"
            base_traffic_to_key[traffic_key] = traffic
    forecast_traffic_to_update = []
    for copy_intent in copy_intent_list:
        if not copy_intent.copied.scenario.is_base:
            traffic = copy_intent.copied
            traffic_key = f"{traffic.region_from_id}__{traffic.region_to_id}__{traffic.interval_id}"
            traffic.base_traffic = base_traffic_to_key[traffic_key]
            forecast_traffic_to_update.append(traffic)
    RegionTraffic.objects.bulk_update(forecast_traffic_to_update, ["base_traffic"])


SCENARIO_MODEL_COPY_CONFIG = ModelCopyConfig(
    model=Scenario,
    field_copy_actions={
        "name": TAKE_FROM_ORIGIN,
        "scenario_id": TAKE_FROM_ORIGIN,
        "is_base": TAKE_FROM_ORIGIN,
        "year": TAKE_FROM_ORIGIN,
        "nodes": MakeCopy(
            ModelCopyConfig(
                model=Node,
                field_copy_actions={
                    "point": TAKE_FROM_ORIGIN,
                    "stops": MakeCopy(
                        ModelCopyConfig(
                            model=Stop,
                            field_copy_actions={
                                "project": UpdateToCopied(Project),
                                "stop_id": TAKE_FROM_ORIGIN,
                                "stop_name": TAKE_FROM_ORIGIN,
                            },
                        ),
                    ),
                },
            ),
        ),
    },
    compound_copy_actions=[
        ModelCopyConfig(
            model=Edge,
            field_copy_actions={
                "scenario": UpdateToCopied(Scenario),
                "first_node": UpdateToCopied(Node),
                "last_node": UpdateToCopied(Node),
                "source_edge_id": TAKE_FROM_ORIGIN,
                "length": TAKE_FROM_ORIGIN,
                "vehicle_types": UpdateToCopied(VehicleType),
                "banned_edges": UpdateToCopied(Edge),
                "pedestrian_speed": TAKE_FROM_ORIGIN,
                "cost": TAKE_FROM_ORIGIN,
                "zone": TAKE_FROM_ORIGIN,
                "lane_num": TAKE_FROM_ORIGIN,
                "parking_cost": TAKE_FROM_ORIGIN,
                "vehicle_speeds": MakeCopy(
                    ModelCopyConfig(
                        model=EdgeVehicleSpeed,
                        field_copy_actions={
                            "interval": UpdateToCopied(Interval),
                            "vehicle_type": UpdateToCopied(VehicleType),
                            "speed_raw": TAKE_FROM_ORIGIN,
                            "speed_dedicated_lane_raw": TAKE_FROM_ORIGIN,
                            "dedicated_lane": TAKE_FROM_ORIGIN,
                        },
                    ),
                ),
                "is_removed": TAKE_FROM_ORIGIN,
            },
        ),
        ModelCopyConfig(
            model=Route,
            field_copy_actions={
                "vehicle_type": UpdateToCopied(VehicleType),
                "scenario": UpdateToCopied(Scenario),
                "attributes": UpdateToCopied(RouteAttribute),
                "source_route_id": TAKE_FROM_ORIGIN,
                "route_number": TAKE_FROM_ORIGIN,
                "route_long_name": TAKE_FROM_ORIGIN,
                "is_circle": TAKE_FROM_ORIGIN,
                "carrier": TAKE_FROM_ORIGIN,
                "communication_type": TAKE_FROM_ORIGIN,
                "season": TAKE_FROM_ORIGIN,
                "regular_transportation_type": TAKE_FROM_ORIGIN,
                "variants": MakeCopy(
                    ModelCopyConfig(
                        model=RouteVariant,
                        field_copy_actions={
                            "variant_number": TAKE_FROM_ORIGIN,
                            "variant_name": TAKE_FROM_ORIGIN,
                            "tariff_id": TAKE_FROM_ORIGIN,
                            "tariff": TAKE_FROM_ORIGIN,
                            "directions": MakeCopy(
                                ModelCopyConfig(
                                    model=RouteDirection,
                                    field_copy_actions={
                                        "direction": TAKE_FROM_ORIGIN,
                                        "length": TAKE_FROM_ORIGIN,
                                        "direction_name": TAKE_FROM_ORIGIN,
                                        "number_of_trips": TAKE_FROM_ORIGIN,
                                    },
                                ),
                            ),
                        },
                    ),
                ),
                "vehicle_count": MakeCopy(
                    ModelCopyConfig(
                        model=RouteVehicleCount,
                        field_copy_actions={
                            "vehicle_class": UpdateToCopied(VehicleClass),
                            "count": TAKE_FROM_ORIGIN,
                        },
                    ),
                ),
            },
        ),
        ModelCopyConfig(
            model=RouteDirectionNode,
            field_copy_actions={
                "route_direction": UpdateToCopied(RouteDirection),
                "node": UpdateToCopied(Node),
                "stop": UpdateToCopied(Stop),
                "order": TAKE_FROM_ORIGIN,
            },
        ),
        ModelCopyConfig(
            model=RouteDirectionEdge,
            field_copy_actions={
                "direction_node_from": UpdateToCopied(RouteDirectionNode),
                "direction_node_to": UpdateToCopied(RouteDirectionNode),
            },
        ),
        ModelCopyConfig(
            model=RouteDirectionEdgeOrder,
            field_copy_actions={
                "edge": UpdateToCopied(Edge),
                "route_direction_edge": UpdateToCopied(RouteDirectionEdge),
                "order": TAKE_FROM_ORIGIN,
            },
        ),
        ModelCopyConfig(
            model=RegionTraffic,
            static_filters=Q(forecast__isnull=True),
            postcopy_steps=[
                PostcopyStep(
                    action=DataModificationActions.EXECUTE_FUNC,
                    func=set_base_region_traffic,
                ),
            ],
            field_copy_actions={
                "region_from": UpdateToCopied(Region),
                "region_to": UpdateToCopied(Region),
                "scenario": UpdateToCopied(Scenario),
                "interval": UpdateToCopied(Interval),
                "traffic": TAKE_FROM_ORIGIN,
                "traffic_car": TAKE_FROM_ORIGIN,
                "traffic_pass": TAKE_FROM_ORIGIN,
                "traffic_pass_uncut": TAKE_FROM_ORIGIN,
                "ttc": TAKE_FROM_ORIGIN,
                "source": TAKE_FROM_ORIGIN,
            },
        ),
    ],
)


PROJECT_COPY_CONFIG = ModelCopyConfig(
    model=Project,
    filter_field_to_input_key={"id": "project_id"},
    field_copy_actions={
        "name": TAKE_FROM_ORIGIN,
        "source_files": MakeCopy(
            ModelCopyConfig(
                model=ProjectFile,
                field_copy_actions={
                    "file": TAKE_FROM_ORIGIN,
                    "error_messages": TAKE_FROM_ORIGIN,
                },
            ),
        ),
        "intervals": MakeCopy(
            ModelCopyConfig(
                model=Interval,
                field_copy_actions={
                    "interval_id": TAKE_FROM_ORIGIN,
                    "interval_name": TAKE_FROM_ORIGIN,
                    "day_type": TAKE_FROM_ORIGIN,
                    "interval_start": TAKE_FROM_ORIGIN,
                    "interval_end": TAKE_FROM_ORIGIN,
                    "rush_hour": TAKE_FROM_ORIGIN,
                    "rush_hour_fraction": TAKE_FROM_ORIGIN,
                },
            ),
        ),
        "region_types": MakeCopy(
            ModelCopyConfig(
                model=RegionType,
                field_copy_actions={
                    "name": TAKE_FROM_ORIGIN,
                },
            ),
        ),
        "municipalities": MakeCopy(MUNICIPALITIES_MODEL_COPY_CONFIG),
        "categories": MakeCopy(
            ModelCopyConfig(
                model=Category,
                field_copy_actions={
                    "name": TAKE_FROM_ORIGIN,
                    "category_id": TAKE_FROM_ORIGIN,
                    "is_public": TAKE_FROM_ORIGIN,
                },
            ),
        ),
        "behavior_types": MakeCopy(BEHAVIOR_TYPE_MODEL_COPY_CONFIG),
        "vehicle_types": MakeCopy(VEHICLE_TYPE_MODEL_COPY_CONFIG),
        "scenarios": MakeCopy(SCENARIO_MODEL_COPY_CONFIG),
        "indicators": MakeCopy(
            ModelCopyConfig(
                model=Indicator,
                field_copy_actions={
                    "name": TAKE_FROM_ORIGIN,
                    "vehicle_type": UpdateToCopied(VehicleType),
                    "category": UpdateToCopied(Category),
                    "value": TAKE_FROM_ORIGIN,
                },
            )
        ),
        "indicator_strings": MakeCopy(
            ModelCopyConfig(
                model=IndicatorString,
                field_copy_actions={
                    "name": TAKE_FROM_ORIGIN,
                    "vehicle_type": UpdateToCopied(VehicleType),
                    "category": UpdateToCopied(Category),
                    "value": TAKE_FROM_ORIGIN,
                },
            )
        ),
    },
)
