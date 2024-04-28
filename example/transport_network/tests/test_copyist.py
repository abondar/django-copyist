import pytest

from django_copyist.config import (
    TAKE_FROM_ORIGIN,
    CopyActions,
    FieldCopyConfig,
    ModelCopyConfig,
)
from django_copyist.copy_request import AbortReason, CopyRequest
from django_copyist.copyist import Copyist, CopyistConfig
from example.transport_network.models import (
    BehaviorCategoryValue,
    BehaviorType,
    Category,
    Edge,
    Forecast,
    Municipality,
    Node,
    Project,
    ProjectShape,
    RegionTraffic,
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
)
from example.transport_network.network_copy_config import ROUTE_NETWORK_COPY_CONFIG
from example.transport_network.project_copy_config import PROJECT_COPY_CONFIG
from example.transport_network.tests.factories import (
    EdgeFactory,
    IntervalFactory,
    RegionFactory,
    RouteFactory,
    VehicleTypeFactory,
)


@pytest.mark.django_db
def test_make_single_copy():
    project = Project.objects.create(
        name="Test project",
    )
    scenario = Scenario.objects.create(
        project=project,
        name="Test scenario",
        scenario_id=1,
        year=2021,
    )
    node = Node.objects.create(scenario=scenario, point="1.1")

    config = CopyistConfig(
        model_configs=[
            ModelCopyConfig(
                model=Node,
                filter_field_to_input_key={"id": "node_id"},
                field_copy_actions={
                    "scenario": TAKE_FROM_ORIGIN,
                    "point": TAKE_FROM_ORIGIN,
                },
            )
        ]
    )

    copyist = Copyist(
        CopyRequest(config=config, input_data={"node_id": node.id}, confirm_write=False)
    )
    result = copyist.execute_copy_request()
    assert result.is_copy_successful, result.reason
    output_map = result.output_map

    model_name = Node.__name__
    assert model_name in output_map, output_map
    copy_id = output_map[model_name][str(node.id)]
    assert copy_id
    copy = Node.objects.get(id=copy_id)

    assert copy.id != node.id
    assert copy.scenario_id == node.scenario_id
    assert copy.point == node.point


@pytest.mark.django_db
def test_make_copy_with_nested_copies():
    project = Project.objects.create(name="Test project")
    Scenario.objects.create(
        project=project,
        name="Test scenario",
        scenario_id=1,
        year=2021,
    )
    Scenario.objects.create(
        project=project,
        name="Test scenario 2",
        scenario_id=2,
        year=1970,
    )

    config = CopyistConfig(
        model_configs=[
            ModelCopyConfig(
                model=Project,
                filter_field_to_input_key={"id": "project_id"},
                field_copy_actions={
                    "name": TAKE_FROM_ORIGIN,
                    "scenarios": FieldCopyConfig(
                        action=CopyActions.MAKE_COPY,
                        copy_with_config=ModelCopyConfig(
                            model=Scenario,
                            field_copy_actions={
                                "name": TAKE_FROM_ORIGIN,
                                "scenario_id": TAKE_FROM_ORIGIN,
                                "year": TAKE_FROM_ORIGIN,
                            },
                        ),
                    ),
                },
            )
        ]
    )

    copyist = Copyist(
        CopyRequest(
            config=config, input_data={"project_id": project.id}, confirm_write=False
        )
    )
    result = copyist.execute_copy_request()
    assert result.is_copy_successful, result.reason
    output_map = result.output_map

    model_name = Project.__name__
    scenario_model_name = Scenario.__name__
    assert model_name in output_map, output_map
    assert scenario_model_name in output_map, output_map
    copy_id = output_map[model_name][str(project.id)]
    assert copy_id
    copy = Project.objects.get(id=copy_id)

    assert copy.id != project.id
    assert copy.name == project.name

    for original_id, copy_scenario_id in output_map[scenario_model_name].items():
        original = Scenario.objects.get(id=original_id)
        copy_scenario = Scenario.objects.get(id=copy_scenario_id)

        assert original.name == copy_scenario.name
        assert original.project_id == project.id
        assert copy_scenario.project_id == copy.id
        assert copy_scenario.project_id != original.project_id


@pytest.mark.django_db
@pytest.mark.parametrize(
    "config",
    [
        CopyistConfig(
            model_configs=[
                ModelCopyConfig(
                    model=Project,
                    filter_field_to_input_key={"id": "project_id"},
                    field_copy_actions={
                        "name": TAKE_FROM_ORIGIN,
                        "categories": FieldCopyConfig(
                            action=CopyActions.MAKE_COPY,
                            copy_with_config=ModelCopyConfig(
                                model=Category,
                                field_copy_actions={
                                    "name": TAKE_FROM_ORIGIN,
                                    "category_id": TAKE_FROM_ORIGIN,
                                    "is_public": TAKE_FROM_ORIGIN,
                                },
                            ),
                        ),
                        "behavior_types": FieldCopyConfig(
                            action=CopyActions.MAKE_COPY,
                            copy_with_config=ModelCopyConfig(
                                model=BehaviorType,
                                field_copy_actions={
                                    "name": TAKE_FROM_ORIGIN,
                                    "behavior_id": TAKE_FROM_ORIGIN,
                                    "apply_remote_percent": TAKE_FROM_ORIGIN,
                                    "category_values": FieldCopyConfig(
                                        action=CopyActions.MAKE_COPY,
                                        copy_with_config=ModelCopyConfig(
                                            model=BehaviorCategoryValue,
                                            field_copy_actions={
                                                "category": FieldCopyConfig(
                                                    action=CopyActions.UPDATE_TO_COPIED,
                                                    reference_to=Category,
                                                ),
                                                "value": TAKE_FROM_ORIGIN,
                                            },
                                        ),
                                    ),
                                },
                            ),
                        ),
                    },
                )
            ]
        ),
        CopyistConfig(
            model_configs=[
                ModelCopyConfig(
                    model=Project,
                    filter_field_to_input_key={"id": "project_id"},
                    field_copy_actions={
                        "name": TAKE_FROM_ORIGIN,
                        "categories": FieldCopyConfig(
                            action=CopyActions.MAKE_COPY,
                            copy_with_config=ModelCopyConfig(
                                model=Category,
                                field_copy_actions={
                                    "name": TAKE_FROM_ORIGIN,
                                    "category_id": TAKE_FROM_ORIGIN,
                                    "is_public": TAKE_FROM_ORIGIN,
                                },
                            ),
                        ),
                        "behavior_types": FieldCopyConfig(
                            action=CopyActions.MAKE_COPY,
                            copy_with_config=ModelCopyConfig(
                                model=BehaviorType,
                                field_copy_actions={
                                    "name": TAKE_FROM_ORIGIN,
                                    "behavior_id": TAKE_FROM_ORIGIN,
                                    "apply_remote_percent": TAKE_FROM_ORIGIN,
                                },
                            ),
                        ),
                    },
                    compound_copy_actions=[
                        ModelCopyConfig(
                            model=BehaviorCategoryValue,
                            field_copy_actions={
                                "category": FieldCopyConfig(
                                    action=CopyActions.UPDATE_TO_COPIED,
                                    reference_to=Category,
                                ),
                                "behavior_type": FieldCopyConfig(
                                    action=CopyActions.UPDATE_TO_COPIED,
                                    reference_to=BehaviorType,
                                ),
                                "value": TAKE_FROM_ORIGIN,
                            },
                        )
                    ],
                )
            ]
        ),
    ],
)
def test_update_to_copied(config):
    project = Project.objects.create(name="Test project")
    bt1 = BehaviorType.objects.create(
        project=project, name="bt1", behavior_id=1, apply_remote_percent=True
    )
    bt2 = BehaviorType.objects.create(
        project=project, name="bt2", behavior_id=2, apply_remote_percent=False
    )
    c1 = Category.objects.create(
        project=project, name="c1", category_id=1, is_public=True
    )
    c2 = Category.objects.create(
        project=project, name="c2", category_id=2, is_public=False
    )

    BehaviorCategoryValue.objects.create(behavior_type=bt1, category=c1, value=1.5)
    BehaviorCategoryValue.objects.create(behavior_type=bt1, category=c2, value=2.5)
    BehaviorCategoryValue.objects.create(behavior_type=bt2, category=c2, value=3.5)

    copyist = Copyist(
        CopyRequest(
            config=config, input_data={"project_id": project.id}, confirm_write=False
        )
    )
    result = copyist.execute_copy_request()
    assert result.is_copy_successful, result.reason
    output_map = result.output_map

    assert Category.__name__ in output_map
    assert BehaviorType.__name__ in output_map
    assert Project.__name__ in output_map
    assert BehaviorCategoryValue.__name__ in output_map

    copy_project = Project.objects.get(id=output_map[Project.__name__][str(project.id)])
    category_copies = list(copy_project.categories.all())
    assert len(category_copies) == 2
    for copy_category in category_copies:
        assert str(copy_category.pk) in output_map[Category.__name__].values()
        assert copy_category.pk not in [c1.pk, c2.pk]

        if copy_category.name == c1.name:
            original = c1
        else:
            original = c2
        copy_values = list(copy_category.behavior_values.all())
        original_values = list(original.behavior_values.all())

        assert {v.value for v in copy_values} == {v.value for v in original_values}
        assert {str(v.pk) for v in copy_values}.issubset(
            output_map[BehaviorCategoryValue.__name__].values()
        )
        assert {str(v.pk) for v in original_values}.issubset(
            output_map[BehaviorCategoryValue.__name__].keys()
        )


@pytest.mark.django_db
def test_copy_project():
    original_project = Project.objects.create(name="project_original")
    original_scenario = Scenario.objects.create(
        name="original_scenario",
        project=original_project,
        scenario_id=1,
        year=2021,
        is_base=True,
    )

    shape = ProjectShape.objects.create(project=original_project, content="123")

    municipality = Municipality.objects.create(project=original_project, name="m1")
    region1 = RegionFactory(project=original_project, municipality=municipality)
    region2 = RegionFactory(project=original_project, municipality=municipality)
    interval = IntervalFactory(project=original_project)

    forecast = Forecast.objects.create(name="f1", shape=shape)
    region_traffic_base = RegionTraffic.objects.create(
        region_from=region1,
        region_to=region2,
        traffic=1,
        scenario=original_scenario,
        interval=interval,
        source="test",
    )
    RegionTraffic.objects.create(
        region_from=region1,
        region_to=region2,
        traffic=1,
        scenario=original_scenario,
        interval=interval,
        source="test",
        base_traffic=region_traffic_base,
        forecast=forecast,
    )

    original_node_1 = Node.objects.create(
        scenario=original_scenario,
        point="1.1",
    )
    original_node_2 = Node.objects.create(
        scenario=original_scenario,
        point="1.2",
    )
    original_node_3 = Node.objects.create(
        scenario=original_scenario,
        point="2.2",
    )
    original_edge_1 = EdgeFactory(
        source_edge_id=1,
        scenario=original_scenario,
        first_node=original_node_1,
        last_node=original_node_2,
    )
    original_edge_2 = EdgeFactory(
        source_edge_id=2,
        scenario=original_scenario,
        first_node=original_node_2,
        last_node=original_node_3,
    )

    original_route = RouteFactory(
        scenario=original_scenario,
        vehicle_type=VehicleTypeFactory(project=original_project),
    )
    attributes = [
        RouteAttribute.objects.create(
            vehicle_type=original_route.vehicle_type,
            attribute_id=i,
            name=str(i),
            value=str(i),
        )
        for i in range(1, 3)
    ]
    original_route.attributes.add(*attributes)
    vehicle_class = VehicleClass.objects.create(
        vehicle_type=original_route.vehicle_type,
        project=original_project,
        name="vh1",
        area=1,
        capacity=1,
        sits=1,
    )
    RouteVehicleCount.objects.create(
        route=original_route, count=1, vehicle_class=vehicle_class
    )

    original_route_variant = RouteVariant.objects.create(
        route=original_route,
        variant_number="1",
        variant_name="rv1",
    )
    route_direction_1 = RouteDirection.objects.create(
        route_variant=original_route_variant,
        direction_name="d1",
    )
    RouteDirection.objects.create(
        route_variant=original_route_variant, direction_name="d2", direction=True
    )
    rdn_1 = RouteDirectionNode.objects.create(
        route_direction=route_direction_1,
        node=original_node_1,
        order=1,
    )
    rdn_2 = RouteDirectionNode.objects.create(
        route_direction=route_direction_1,
        node=original_node_2,
        order=2,
    )
    rdn_3 = RouteDirectionNode.objects.create(
        route_direction=route_direction_1,
        node=original_node_3,
        order=3,
    )
    rde_1 = RouteDirectionEdge.objects.create(
        direction_node_from=rdn_1, direction_node_to=rdn_2
    )
    rde_2 = RouteDirectionEdge.objects.create(
        direction_node_from=rdn_2, direction_node_to=rdn_3
    )
    RouteDirectionEdgeOrder.objects.create(
        route_direction_edge=rde_1,
        order=1,
        edge=original_edge_1,
    )
    RouteDirectionEdgeOrder.objects.create(
        route_direction_edge=rde_2,
        order=1,
        edge=original_edge_1,
    )
    RouteDirectionEdgeOrder.objects.create(
        route_direction_edge=rde_2,
        order=2,
        edge=original_edge_2,
    )

    result = Copyist(
        copy_request=CopyRequest(
            input_data={
                "project_id": original_project.pk,
            },
            config=CopyistConfig(model_configs=[PROJECT_COPY_CONFIG]),
            confirm_write=False,
        )
    ).execute_copy_request()

    assert result.is_copy_successful, (
        result.reason,
        result.set_to_filter_map,
        result.ignored_map,
    )
    copied_project = Project.objects.last()
    assert copied_project.pk != original_project.pk
    assert copied_project.name == original_project.name

    copied_scenario = Scenario.objects.last()
    assert copied_scenario.pk != original_scenario.pk
    assert copied_scenario.name == original_scenario.name
    assert copied_scenario.scenario_id == original_scenario.scenario_id

    copied_node_1 = Node.objects.filter(point=original_node_1.point).last()
    assert copied_node_1.pk != original_node_1.pk
    assert copied_node_1.scenario_id != original_node_1.scenario_id

    copied_edge_list = list(Edge.objects.filter(scenario=copied_scenario))
    assert len(copied_edge_list) == 2
    assert {e.pk for e in copied_edge_list} != {original_edge_1.pk, original_edge_2.pk}
    assert {e.source_edge_id for e in copied_edge_list} == {
        original_edge_1.source_edge_id,
        original_edge_2.source_edge_id,
    }

    traffic = list(RegionTraffic.objects.filter(scenario__project=copied_project))
    assert len(traffic) == 1
    assert traffic[0].base_traffic is None


MISSING_TARGET_NODE = "MISSING_TARGET_NODE"
MISSING_TARGET_EDGE = "MISSING_TARGET_EDGE"
MISSING_STOP = "MISSING_STOP"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ["features", "expected_reason"],
    [
        [[], None],
        [[MISSING_TARGET_EDGE], AbortReason.IGNORED],
        [
            [MISSING_TARGET_NODE, MISSING_TARGET_EDGE],
            AbortReason.IGNORED,
        ],
        [[MISSING_STOP], AbortReason.IGNORED],
    ],
)
def test_copy_network(expected_reason, features):  # flake8: noqa
    project = Project.objects.create(name="project_original")
    original_scenario = Scenario.objects.create(
        name="original_scenario", project=project, scenario_id=1, year=2021
    )
    target_scenario = Scenario.objects.create(
        name="target_scenario", project=project, scenario_id=1, year=2022
    )
    vt_1 = VehicleTypeFactory(project=project)
    vt_2 = VehicleTypeFactory(project=project)

    original_node_1 = Node.objects.create(
        scenario=original_scenario,
        point="1.1",
    )
    origin_stop = Stop.objects.create(
        project=project,
        stop_id=1,
        stop_name="stop1",
        node=original_node_1,
    )
    original_node_2 = Node.objects.create(
        scenario=original_scenario,
        point="1.2",
    )
    original_node_3 = Node.objects.create(
        scenario=original_scenario,
        point="2.2",
    )
    target_node_1 = Node.objects.create(
        scenario=target_scenario,
        point="1.1",
    )
    target_node_2 = Node.objects.create(
        scenario=target_scenario,
        point="1.2",
    )
    if MISSING_STOP not in features:
        target_stop = Stop.objects.create(
            project=project,
            stop_id=1,
            stop_name="stop1",
            node=target_node_1,
        )
    if MISSING_TARGET_NODE not in features:
        target_node_3 = Node.objects.create(
            scenario=target_scenario,
            point="2.2",
        )
    original_edge_1 = EdgeFactory(
        source_edge_id=1,
        scenario=original_scenario,
        first_node=original_node_1,
        last_node=original_node_2,
    )
    original_edge_2 = EdgeFactory(
        source_edge_id=2,
        scenario=original_scenario,
        first_node=original_node_2,
        last_node=original_node_3,
    )
    target_edge_1 = EdgeFactory(
        source_edge_id=1,
        scenario=target_scenario,
        first_node=target_node_1,
        last_node=target_node_2,
    )
    for edge in [original_edge_1, original_edge_2]:
        edge.vehicle_types.add(vt_1, vt_2)
    target_edge_1.vehicle_types.add(vt_1)
    if MISSING_TARGET_EDGE not in features:
        target_edge_2 = EdgeFactory(
            source_edge_id=2,
            scenario=target_scenario,
            first_node=target_node_2,
            last_node=target_node_3,
        )
        target_edge_2.vehicle_types.add(vt_1)

    original_route = RouteFactory(scenario=original_scenario, vehicle_type=vt_1)
    routes_to_populate = [original_route]

    attributes = [
        RouteAttribute.objects.create(
            vehicle_type=original_route.vehicle_type,
            attribute_id=i,
            name=str(i),
            value=str(i),
        )
        for i in range(1, 3)
    ]
    original_route.attributes.add(*attributes)
    vehicle_class = VehicleClass.objects.create(
        vehicle_type=original_route.vehicle_type,
        project=project,
        name="vh1",
        area=1,
        capacity=1,
        sits=1,
    )
    vehicle_count = RouteVehicleCount.objects.create(
        route=original_route, count=1, vehicle_class=vehicle_class
    )

    for route in routes_to_populate:
        route_variant = RouteVariant.objects.create(
            route=route,
            variant_number="1",
            variant_name="rv1",
        )
        route_direction_1 = RouteDirection.objects.create(
            route_variant=route_variant,
            direction_name="d1",
        )
        route_direction_2 = RouteDirection.objects.create(
            route_variant=route_variant, direction_name="d2", direction=True
        )
        rdn_1 = RouteDirectionNode.objects.create(
            route_direction=route_direction_1,
            node=original_node_1,
            order=1,
            stop=origin_stop,
        )
        rdn_2 = RouteDirectionNode.objects.create(
            route_direction=route_direction_1,
            node=original_node_2,
            order=2,
        )
        rdn_3 = RouteDirectionNode.objects.create(
            route_direction=route_direction_1,
            node=original_node_3,
            order=3,
        )
        rde_1 = RouteDirectionEdge.objects.create(
            direction_node_from=rdn_1, direction_node_to=rdn_2
        )
        rde_2 = RouteDirectionEdge.objects.create(
            direction_node_from=rdn_2, direction_node_to=rdn_3
        )
        RouteDirectionEdgeOrder.objects.create(
            route_direction_edge=rde_1,
            order=1,
            edge=original_edge_1,
        )
        RouteDirectionEdgeOrder.objects.create(
            route_direction_edge=rde_2,
            order=1,
            edge=original_edge_1,
        )
        RouteDirectionEdgeOrder.objects.create(
            route_direction_edge=rde_2,
            order=2,
            edge=original_edge_2,
        )

    result = Copyist(
        copy_request=CopyRequest(
            input_data={
                "origin_scenario_id": original_scenario.pk,
                "target_scenario_id": target_scenario.pk,
            },
            config=CopyistConfig(model_configs=[ROUTE_NETWORK_COPY_CONFIG]),
            confirm_write=False,
        ),
    ).execute_copy_request()

    if expected_reason is None:
        assert result.is_copy_successful
        assert result.reason is None
        route_copy = Route.objects.last()
        assert route_copy.pk != original_route.pk
        assert route_copy.route_number == original_route.route_number
        assert route_copy.scenario_id == target_scenario.pk
        assert route_copy.vehicle_type_id == original_route.vehicle_type_id

        copy_attributes = list(route_copy.attributes.all())
        assert len(copy_attributes) == 2
        assert {a.pk for a in copy_attributes} != {a.pk for a in attributes}
        assert {(a.attribute_id, a.name, a.value) for a in copy_attributes} == {
            (a.attribute_id, a.name, a.value) for a in attributes
        }

        copy_vehicle_count = RouteVehicleCount.objects.last()
        assert copy_vehicle_count.pk != vehicle_count
        assert copy_vehicle_count.count == vehicle_count.count

        copy_route_variant = RouteVariant.objects.last()
        assert copy_route_variant.pk != route_variant.pk
        assert copy_route_variant.variant_name == route_variant.variant_name
        assert copy_route_variant.variant_number == route_variant.variant_number

        copy_directions = list(copy_route_variant.directions.all())
        original_directions = (route_direction_1, route_direction_2)
        assert len(copy_directions) == 2
        assert {d.pk for d in copy_directions} != {d.pk for d in original_directions}
        assert {d.direction_name for d in copy_directions} == {
            d.direction_name for d in original_directions
        }

        copy_direction = next(
            d
            for d in copy_directions
            if d.direction_name == route_direction_1.direction_name
        )
        copy_rdn_list = list(copy_direction.path_nodes.all())
        assert len(copy_rdn_list) == 3
        assert {r.node_id for r in copy_rdn_list} != {
            r.node_id for r in (rdn_1, rdn_2, rdn_3)
        }
        assert {r.node.point for r in copy_rdn_list} == {
            r.node.point for r in (rdn_1, rdn_2, rdn_3)
        }
        assert all(r.node.scenario_id == target_scenario.pk for r in copy_rdn_list)
        copy_rdn_1 = next(
            rdn for rdn in copy_rdn_list if rdn.node.point == rdn_1.node.point
        )
        assert copy_rdn_1.stop_id == target_stop.pk

        copy_node_id_list = [r.pk for r in copy_rdn_list]
        copy_rde_list = list(
            RouteDirectionEdge.objects.filter(
                direction_node_from_id__in=copy_node_id_list,
                direction_node_to_id__in=copy_node_id_list,
            )
        )
        assert len(copy_rde_list) == 2

        copy_rdeo_list = list(
            RouteDirectionEdgeOrder.objects.filter(
                route_direction_edge_id__in=[c.pk for c in copy_rde_list]
            )
        )
        assert len(copy_rdeo_list) == 3
        assert {c.edge_id for c in copy_rdeo_list} == {
            e.id for e in (target_edge_1, target_edge_2)
        }
    elif expected_reason == AbortReason.IGNORED:
        assert not result.is_copy_successful
        assert result.reason == expected_reason

        if {MISSING_TARGET_NODE, MISSING_TARGET_EDGE, MISSING_STOP} & set(features):
            ignored_directions = [route_direction_1.pk]
            assert set(result.ignored_map.get(RouteDirection.__name__)) == set(
                ignored_directions
            ), result.ignored_map
        if MISSING_TARGET_NODE in features:
            assert (
                result.set_to_filter_map[RouteDirectionNode.__name__]["node"][
                    str(original_node_3.pk)
                ]
                is None
            )
        if MISSING_TARGET_EDGE in features:
            assert (
                result.set_to_filter_map[RouteDirectionEdgeOrder.__name__]["edge"][
                    str(original_edge_2.pk)
                ]
                is None
            )
        if MISSING_STOP in features:
            assert (
                result.set_to_filter_map[RouteDirectionNode.__name__]["stop"][
                    str(origin_stop.pk)
                ]
                is None
            )
