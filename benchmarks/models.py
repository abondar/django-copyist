"""
A kanban board: Board -> Column -> Task -> ChecklistItem, with Task <-> Tag links.

The models carry django-clone's CloneMixin so that both libraries copy the same tree.
"""

from django.db import models
from model_clone import CloneMixin


class Tag(models.Model):
    name = models.CharField(max_length=50)


class Board(CloneMixin, models.Model):
    name = models.CharField(max_length=100)

    _clone_m2o_or_o2m_fields = ["columns"]


class Column(CloneMixin, models.Model):
    board = models.ForeignKey(Board, related_name="columns", on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    position = models.IntegerField()

    _clone_m2o_or_o2m_fields = ["tasks"]


class Task(CloneMixin, models.Model):
    column = models.ForeignKey(Column, related_name="tasks", on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    description = models.TextField()
    priority = models.IntegerField()
    tags = models.ManyToManyField(Tag, related_name="tasks")

    _clone_m2o_or_o2m_fields = ["checklist_items"]
    _clone_linked_m2m_fields = ["tags"]


class ChecklistItem(CloneMixin, models.Model):
    task = models.ForeignKey(Task, related_name="checklist_items", on_delete=models.CASCADE)
    text = models.CharField(max_length=200)
    done = models.BooleanField()
