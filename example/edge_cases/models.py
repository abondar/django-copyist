"""
Models that cover edge cases of the copy engine.

They are not meant as usage examples. See ``example.demo`` for those.
"""

import uuid

from django.db import models


class Project(models.Model):
    """Has the same class name as ``demo.Project`` and ``transport_network.Project``."""

    name = models.CharField(max_length=100)


class Tag(models.Model):
    name = models.CharField(max_length=100)


class Item(models.Model):
    project = models.ForeignKey(Project, related_name="items", on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    position = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    tags = models.ManyToManyField(Tag, related_name="items", blank=True)


class Stage(models.Model):
    project = models.ForeignKey(Project, related_name="stages", on_delete=models.CASCADE)
    name = models.CharField(max_length=100)


class Label(models.Model):
    project = models.ForeignKey(Project, related_name="labels", on_delete=models.CASCADE)
    name = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "name"], name="unique_label_name"),
        ]


class Card(models.Model):
    """References two copied models through nullable foreign keys only."""

    name = models.CharField(max_length=100)
    stage = models.ForeignKey(
        Stage, null=True, blank=True, related_name="cards", on_delete=models.CASCADE
    )
    label = models.ForeignKey(
        Label, null=True, blank=True, related_name="cards", on_delete=models.CASCADE
    )


class Folder(models.Model):
    """Primary key is not called ``id``."""

    folder_code = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)


class Document(models.Model):
    doc_code = models.AutoField(primary_key=True)
    folder = models.ForeignKey(Folder, related_name="documents", on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    tags = models.ManyToManyField(Tag, related_name="documents", blank=True)


class Workspace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)


class Page(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, related_name="pages", on_delete=models.CASCADE)
    title = models.CharField(max_length=100)
    tags = models.ManyToManyField(Tag, related_name="pages", blank=True)


class Note(models.Model):
    """Has no ``objects`` manager."""

    project = models.ForeignKey(Project, related_name="notes", on_delete=models.CASCADE)
    text = models.CharField(max_length=100)

    records = models.Manager()


class Place(models.Model):
    name = models.CharField(max_length=100)


class Restaurant(Place):
    """Multi-table inheritance. ``bulk_create`` does not support it."""

    serves_pizza = models.BooleanField(default=False)


class Ticket(models.Model):
    project = models.ForeignKey(Project, related_name="tickets", on_delete=models.CASCADE)
    title = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    priority = models.IntegerField(default=1)
    watchers = models.ManyToManyField(Tag, through="TicketWatcher", related_name="tickets")


class TicketWatcher(models.Model):
    """Custom ``through`` model with a required extra column."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE)
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)
    role = models.CharField(max_length=20)


class Category(models.Model):
    """Self-referencing tree."""

    project = models.ForeignKey(Project, related_name="categories", on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    parent = models.ForeignKey(
        "self", null=True, blank=True, related_name="children", on_delete=models.CASCADE
    )


class Country(models.Model):
    """Primary key set by hand, without a default."""

    code = models.CharField(max_length=2, primary_key=True)
    name = models.CharField(max_length=100)
