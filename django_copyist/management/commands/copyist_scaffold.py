from django.apps import apps
from django.core.management.base import BaseCommand, CommandError

from django_copyist.checks import ConfigIssueLevel, check_config
from django_copyist.scaffold import scaffold_config


class Command(BaseCommand):
    help = (
        "Print a starting django-copyist config for a model. It copies plain fields "
        "from the origin and one-to-many children down to --depth levels."
    )

    def add_arguments(self, parser):
        parser.add_argument("model", help="Model label, for example 'shop.Order'.")
        parser.add_argument(
            "--depth",
            type=int,
            default=1,
            help="Levels of one-to-many children to copy with MakeCopy (default: 1).",
        )
        parser.add_argument("--name", help="Name of the generated constant.")
        parser.add_argument("--input-key", help="input_data key that selects the root row.")
        parser.add_argument(
            "--no-check",
            action="store_true",
            help="Do not run check_config() on the generated config.",
        )

    def handle(self, *args, **options):
        try:
            model = apps.get_model(options["model"])
        except (LookupError, ValueError) as e:
            raise CommandError(
                f"Unknown model {options['model']!r}. Use the 'app_label.ModelName' form."
            ) from e

        try:
            source = scaffold_config(
                model,
                depth=options["depth"],
                name=options["name"],
                input_key=options["input_key"],
            )
        except ValueError as e:
            raise CommandError(str(e)) from e

        self.stdout.write(source, ending="")

        if options["no_check"]:
            return
        namespace: dict = {}
        exec(compile(source, "<copyist_scaffold>", "exec"), namespace)
        config = namespace[self._name(source)]
        issues = check_config(config)
        errors = [i for i in issues if i.level == ConfigIssueLevel.ERROR]
        self.stderr.write(
            f"check_config: {len(errors)} error(s), {len(issues) - len(errors)} warning(s)"
        )
        for issue in issues:
            self.stderr.write(f"  {issue}")

    @staticmethod
    def _name(source: str) -> str:
        for line in source.splitlines():
            if " = ModelCopyConfig(" in line:
                return line.split(" = ", 1)[0]
        raise CommandError("Generated source has no config")  # pragma: no cover
