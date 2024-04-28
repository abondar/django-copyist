import random
from datetime import time

import factory.fuzzy
from factory.django import DjangoModelFactory

from example.transport_network.models import (
    CommunicationType,
    Edge,
    Interval,
    Node,
    Project,
    Region,
    RegionType,
    RegularTransportationType,
    Route,
    Scenario,
    Season,
    VehicleType,
)


class ProjectFactory(DjangoModelFactory):
    class Meta:
        model = Project

    name = factory.Faker("pystr")


class ScenarioFactory(DjangoModelFactory):
    class Meta:
        model = Scenario

    name = factory.Faker("pystr")
    scenario_id = factory.Faker("pyint")
    project = factory.SubFactory(ProjectFactory)
    year = factory.Faker("pyint")


class IntervalFactory(DjangoModelFactory):
    class Meta:
        model = Interval

    project = factory.SubFactory(ProjectFactory)
    interval_id = factory.lazy_attribute(lambda o: random.randint(1, 999999999))
    interval_name = factory.Faker("pystr")
    day_type = factory.Faker("pystr")
    interval_start = factory.lazy_attribute(lambda o: time(10, 00))
    interval_end = factory.lazy_attribute(lambda o: time(23, 30))
    rush_hour = factory.Faker("pybool")
    rush_hour_fraction = factory.Faker("pyfloat")


class RegionTypeFactory(DjangoModelFactory):
    class Meta:
        model = RegionType

    project = factory.SubFactory(ProjectFactory)
    name = factory.Faker("pystr")


class RegionFactory(DjangoModelFactory):
    class Meta:
        model = Region

    project = factory.SubFactory(ProjectFactory)
    name = factory.Faker("pystr")
    source_dist_id = factory.Faker("pyint")
    region_type = factory.SubFactory(RegionTypeFactory)


class VehicleTypeFactory(DjangoModelFactory):
    class Meta:
        model = VehicleType

    project = factory.SubFactory(ProjectFactory)
    name = factory.Faker("pystr")
    max_speed = factory.Faker("pyint")
    is_public = factory.Faker("pybool")
    is_editable = True
    transport_type_id = factory.Faker("pyint")


class SeasonFactory(DjangoModelFactory):
    class Meta:
        model = Season

    name = factory.Faker("pystr")


class CommunicationTypeFactory(DjangoModelFactory):
    class Meta:
        model = CommunicationType

    name = factory.Faker("pystr")


class RegularTransportationTypeFactory(DjangoModelFactory):
    class Meta:
        model = RegularTransportationType

    name = factory.Faker("pystr")


class RouteFactory(DjangoModelFactory):
    class Meta:
        model = Route

    vehicle_type = factory.SubFactory(VehicleTypeFactory)
    scenario = factory.SubFactory(ScenarioFactory)
    season = factory.SubFactory(SeasonFactory)
    communication_type = factory.SubFactory(CommunicationTypeFactory)
    regular_transportation_type = factory.SubFactory(RegularTransportationTypeFactory)
    source_route_id = factory.Faker("pyint")
    route_number = factory.Faker("pystr")
    route_long_name = factory.Faker("pystr")
    is_circle = factory.Faker("pybool")
    carrier = factory.Faker("pystr")


class NodeFactory(DjangoModelFactory):
    class Meta:
        model = Node

    scenario = factory.SubFactory(ScenarioFactory)
    point = factory.Faker("str")


class EdgeFactory(DjangoModelFactory):
    class Meta:
        model = Edge

    first_node = factory.SubFactory(NodeFactory)
    last_node = factory.SubFactory(NodeFactory)
    scenario = factory.SubFactory(ScenarioFactory)
    source_edge_id = factory.Faker("pyint")
    length = factory.Faker("pyfloat", positive=True)
    pedestrian_speed = factory.Faker("pyfloat", positive=True)
    cost = factory.Faker("pyfloat", positive=True)
    zone = factory.Faker("pyint")
    lane_num = factory.Faker("pyint")

    @factory.post_generation
    def vehicle_types(self, create, extracted, **kwargs):
        if not create:  # Simple build, do nothing.
            return
        if extracted:  # A list of vehicle types were passed in, use them
            for vt in extracted:
                self.vehicle_types.add(vt)

    @factory.post_generation
    def banned_edges(self, create, extracted, **kwargs):
        if not create:
            return
        if extracted:
            for edge in extracted:
                self.banned_edges.add(edge)
