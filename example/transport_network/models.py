from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class DataFile(models.Model):
    file = models.FileField()
    source_file_name = models.CharField(max_length=255)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="data_files",
        on_delete=models.CASCADE,
    )
    created = models.DateTimeField(auto_now_add=True)


class Project(models.Model):
    name = models.TextField(_("Название проекта"))
    created = models.DateTimeField(_("Дата начала проекта"), auto_now_add=True)
    last_used_date = models.DateTimeField(
        _("Время последнего использования"), default=timezone.now
    )
    last_data_id = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("id",)


class ProjectFile(models.Model):
    project = models.ForeignKey(
        Project, related_name="source_files", on_delete=models.CASCADE
    )
    file = models.ForeignKey(
        DataFile,
        related_name="project_files",
        on_delete=models.CASCADE,
    )
    error_messages = models.JSONField(
        _("Load error messages"), blank=True, default=list
    )


class Municipality(models.Model):
    project = models.ForeignKey(
        Project, related_name="municipalities", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=200)


class RegionType(models.Model):
    project = models.ForeignKey(
        Project, related_name="region_types", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=100)


class Region(models.Model):
    project = models.ForeignKey(
        Project, related_name="regions", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=200)
    source_dist_id = models.IntegerField()
    region_type = models.ForeignKey(
        RegionType, related_name="regions", on_delete=models.CASCADE
    )
    municipality = models.ForeignKey(
        Municipality,
        blank=True,
        null=True,
        related_name="regions",
        on_delete=models.CASCADE,
    )


class Scenario(models.Model):
    project = models.ForeignKey(
        Project, related_name="scenarios", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=100)
    scenario_id = models.IntegerField()
    is_base = models.BooleanField(default=False)
    year = models.PositiveSmallIntegerField()


class Interval(models.Model):
    project = models.ForeignKey(
        Project, related_name="intervals", on_delete=models.CASCADE
    )
    interval_id = models.IntegerField()
    interval_name = models.CharField(max_length=100)
    day_type = models.CharField(max_length=100)
    interval_start = models.TimeField()
    interval_end = models.TimeField()
    rush_hour = models.BooleanField(default=False)
    rush_hour_fraction = models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)]
    )


class Category(models.Model):
    project = models.ForeignKey(
        Project, related_name="categories", on_delete=models.CASCADE
    )
    category_id = models.IntegerField()
    name = models.CharField(max_length=50)
    is_public = models.BooleanField()


class BehaviorType(models.Model):
    project = models.ForeignKey(
        Project, related_name="behavior_types", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=100)
    behavior_id = models.PositiveSmallIntegerField()
    apply_remote_percent = models.BooleanField()


class BehaviorCategoryValue(models.Model):
    behavior_type = models.ForeignKey(
        BehaviorType, on_delete=models.CASCADE, related_name="category_values"
    )
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name="behavior_values"
    )
    value = models.FloatField()


class VehicleType(models.Model):
    project = models.ForeignKey(
        Project, related_name="vehicle_types", on_delete=models.CASCADE
    )
    name = models.CharField(_("type ts"), max_length=32)
    max_speed = models.IntegerField()
    is_public = models.BooleanField()
    is_editable = models.BooleanField()
    transport_type_id = models.IntegerField()


class VehicleClass(models.Model):
    project = models.ForeignKey(
        Project, related_name="vehicle_classes", on_delete=models.CASCADE
    )
    name = models.CharField(_("type ts"), max_length=32)
    vehicle_type = models.ForeignKey(
        VehicleType, related_name="classes", on_delete=models.CASCADE
    )
    sits = models.IntegerField()
    area = models.IntegerField()
    capacity = models.IntegerField()


class Node(models.Model):
    point = models.TextField()
    scenario = models.ForeignKey(
        Scenario, related_name="nodes", on_delete=models.CASCADE
    )


class Edge(models.Model):
    source_edge_id = models.PositiveIntegerField()
    first_node = models.ForeignKey(
        Node, related_name="edges_starts", on_delete=models.CASCADE
    )
    last_node = models.ForeignKey(
        Node, related_name="edges_ends", on_delete=models.CASCADE
    )
    length = models.FloatField()
    scenario = models.ForeignKey(
        Scenario, null=True, blank=True, related_name="edges", on_delete=models.CASCADE
    )
    vehicle_types = models.ManyToManyField(VehicleType, related_name="edges")
    banned_edges = models.ManyToManyField("self")
    pedestrian_speed = models.FloatField()
    cost = models.FloatField()
    zone = models.IntegerField()
    lane_num = models.IntegerField()
    parking_cost = models.FloatField(default=0)
    is_removed = models.BooleanField(default=False)


class EdgeVehicleSpeed(models.Model):
    edge = models.ForeignKey(
        Edge, related_name="vehicle_speeds", on_delete=models.CASCADE
    )
    interval = models.ForeignKey(Interval, on_delete=models.CASCADE)

    vehicle_type = models.ForeignKey(VehicleType, on_delete=models.CASCADE)
    speed_raw = models.FloatField()
    speed_dedicated_lane_raw = models.FloatField()
    dedicated_lane = models.BooleanField()


class Stop(models.Model):
    project = models.ForeignKey(Project, related_name="stops", on_delete=models.CASCADE)
    stop_id = models.PositiveIntegerField(_("stop id"))
    stop_name = models.CharField(_("stop name"), max_length=200)
    node = models.ForeignKey(Node, related_name="stops", on_delete=models.CASCADE)
    route_directions = models.ManyToManyField(
        "RouteDirection", through="RouteDirectionNode"
    )

    def save(self, *args, **kwargs):
        if not self.stop_id:
            with transaction.atomic():
                max_stop_id = Stop.objects.filter(project_id=self.project_id).aggregate(
                    models.Max("stop_id")
                )["stop_id__max"]
                max_stop_id = max_stop_id or 0
                self.stop_id = max_stop_id + 1
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)


class CommunicationType(models.Model):
    name = models.CharField(max_length=100, unique=True)


class Season(models.Model):
    name = models.CharField(max_length=100, unique=True)


class RegularTransportationType(models.Model):
    name = models.CharField(max_length=100, unique=True)


class Route(models.Model):
    source_route_id = models.PositiveIntegerField(_("source_route_id"))
    route_number = models.CharField(_("route number"), max_length=64)
    vehicle_type = models.ForeignKey(
        "VehicleType",
        on_delete=models.CASCADE,
        related_name="routes",
        verbose_name=_("vehicle type"),
    )
    route_long_name = models.CharField(_("route long name"), max_length=200)
    is_circle = models.BooleanField(_("is circle"), default=False)
    carrier = models.CharField(max_length=100)
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE)
    attributes = models.ManyToManyField("RouteAttribute", related_name="routes")
    communication_type = models.ForeignKey(
        CommunicationType, on_delete=models.CASCADE, null=True
    )
    season = models.ForeignKey(Season, on_delete=models.CASCADE, null=True)
    regular_transportation_type = models.ForeignKey(
        RegularTransportationType, on_delete=models.CASCADE, null=True
    )

    def save(self, *args, **kwargs):
        if not self.source_route_id:
            with transaction.atomic():
                max_source_route_id = Route.objects.filter(
                    scenario__project_id=self.scenario.project_id
                ).aggregate(models.Max("source_route_id"))["source_route_id__max"]
                max_source_route_id = max_source_route_id or 0
                self.source_route_id = max_source_route_id + 1
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)


class RouteVariant(models.Model):
    route = models.ForeignKey(Route, related_name="variants", on_delete=models.CASCADE)
    variant_number = models.CharField(_("route number"), max_length=64)
    variant_name = models.CharField(_("variant name"), max_length=200)
    tariff_id = models.IntegerField(default=1)
    tariff = models.IntegerField(default=30)


class RouteVehicleCount(models.Model):
    route = models.ForeignKey(
        Route, related_name="vehicle_count", on_delete=models.CASCADE
    )
    vehicle_class = models.ForeignKey(VehicleClass, on_delete=models.CASCADE)
    count = models.PositiveSmallIntegerField()


class RouteDirection(models.Model):
    route_variant = models.ForeignKey(
        RouteVariant, related_name="directions", on_delete=models.CASCADE
    )
    direction = models.BooleanField(default=False)
    length = models.FloatField(default=0)
    direction_name = models.CharField(_("direction name"), max_length=200)
    number_of_trips = models.PositiveSmallIntegerField(default=0)


class RouteDirectionEdge(models.Model):
    direction_node_from = models.OneToOneField(
        "RouteDirectionNode", related_name="path_out", on_delete=models.CASCADE
    )
    direction_node_to = models.OneToOneField(
        "RouteDirectionNode", related_name="path_in", on_delete=models.CASCADE
    )
    edges = models.ManyToManyField(
        Edge, through="RouteDirectionEdgeOrder", related_name="route_direction_edges"
    )


class RouteDirectionEdgeOrder(models.Model):
    edge = models.ForeignKey(Edge, on_delete=models.CASCADE)
    route_direction_edge = models.ForeignKey(
        RouteDirectionEdge,
        related_name="route_direction_edge_order",
        on_delete=models.CASCADE,
    )
    order = models.PositiveSmallIntegerField()


class RouteDirectionNode(models.Model):
    route_direction = models.ForeignKey(
        RouteDirection, related_name="path_nodes", on_delete=models.CASCADE
    )
    node = models.ForeignKey(Node, related_name="path_nodes", on_delete=models.CASCADE)
    order = models.PositiveSmallIntegerField(default=0)
    stop = models.ForeignKey(
        Stop,
        related_name="route_direction_nodes",
        blank=True,
        null=True,
        on_delete=models.CASCADE,
    )

    class Meta:
        ordering = ("order",)


class RouteAttribute(models.Model):
    vehicle_type = models.ForeignKey(
        VehicleType, related_name="route_attributes", on_delete=models.CASCADE
    )
    attribute_id = models.IntegerField()
    name = models.CharField(max_length=20)
    value = models.CharField(max_length=20)


class ProjectShape(models.Model):
    project = models.ForeignKey(
        Project, related_name="models", on_delete=models.CASCADE
    )
    created = models.DateTimeField(auto_now_add=True)
    content = models.TextField()


class Forecast(models.Model):
    name = models.CharField(max_length=100)
    shape = models.ForeignKey(
        ProjectShape, related_name="forecasts", on_delete=models.CASCADE
    )
    created = models.DateTimeField(auto_now_add=True)
    remote_jobs_percent = models.FloatField(default=0)
    partial_remote_jobs_percent = models.FloatField(default=0)


class RegionTraffic(models.Model):
    forecast = models.ForeignKey(
        Forecast,
        related_name="traffic",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    region_from = models.ForeignKey(
        Region, related_name="region_from_forecast", on_delete=models.CASCADE
    )
    region_to = models.ForeignKey(
        Region, related_name="region_to_forecast", on_delete=models.CASCADE
    )
    traffic = models.FloatField()
    traffic_car = models.FloatField(default=0)
    traffic_pass = models.FloatField(default=0)
    traffic_pass_uncut = models.FloatField(default=0)
    delta_ttc_traffic = models.FloatField(default=0)
    delta_factor_traffic = models.FloatField(default=0)
    public_transport_switch = models.FloatField(default=0)
    base_traffic = models.ForeignKey(
        "self",
        blank=True,
        null=True,
        related_name="forecast_traffic",
        on_delete=models.CASCADE,
    )
    scenario = models.ForeignKey(
        Scenario, blank=True, null=True, on_delete=models.CASCADE
    )
    interval = models.ForeignKey(
        Interval, blank=True, null=True, on_delete=models.CASCADE
    )
    ttc = models.FloatField(blank=True, null=True)
    source = models.CharField(max_length=100)


class Indicator(models.Model):
    name = models.CharField(max_length=100)
    project = models.ForeignKey(
        Project, related_name="indicators", on_delete=models.CASCADE
    )
    vehicle_type = models.ForeignKey(
        VehicleType, blank=True, null=True, on_delete=models.CASCADE
    )
    category = models.ForeignKey(
        Category, blank=True, null=True, on_delete=models.CASCADE
    )
    value = models.FloatField()


class IndicatorString(models.Model):
    name = models.CharField(max_length=100)
    project = models.ForeignKey(
        Project, related_name="indicator_strings", on_delete=models.CASCADE
    )
    vehicle_type = models.ForeignKey(
        VehicleType, blank=True, null=True, on_delete=models.CASCADE
    )
    category = models.ForeignKey(
        Category, blank=True, null=True, on_delete=models.CASCADE
    )
    value = models.CharField(max_length=100)
