from django.db import models


class Company(models.Model):
    name = models.CharField(max_length=100)
    address = models.CharField(max_length=100)


class Project(models.Model):
    name = models.CharField(max_length=100)
    company = models.ForeignKey(
        Company, related_name="projects", on_delete=models.CASCADE
    )


class Employee(models.Model):
    name = models.CharField(max_length=100)
    company = models.ForeignKey(
        Company, related_name="employees", on_delete=models.CASCADE
    )


class Counterpart(models.Model):
    name = models.CharField(max_length=100)
    external_id = models.IntegerField()
    project = models.ForeignKey(
        Project, related_name="counterparts", on_delete=models.CASCADE
    )


class Task(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()

    assignee = models.ForeignKey(
        Employee, related_name="tasks", on_delete=models.CASCADE
    )
    project = models.ForeignKey(Project, related_name="tasks", on_delete=models.CASCADE)
    counterparts = models.ManyToManyField(Counterpart, related_name="tasks")
