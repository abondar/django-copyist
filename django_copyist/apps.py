from django.apps import AppConfig


class DjangoCopyistConfig(AppConfig):
    """
    Add ``"django_copyist"`` to ``INSTALLED_APPS`` to enable the
    ``copyist_scaffold`` management command. The copy API works without it.
    """

    name = "django_copyist"
    verbose_name = "django-copyist"
