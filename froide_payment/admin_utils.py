from django.contrib.admin.filters import SimpleListFilter
from django.utils.translation import gettext_lazy as _


class NullFilter(SimpleListFilter):
    """
    Taken from
    http://stackoverflow.com/questions/7691890/filtering-django-admin-by-null-is-not-null
    under CC-By 3.0
    """

    title = ""

    parameter_name = ""

    def lookups(self, request, model_admin):
        return (
            ("1", _("Has value")),
            ("0", _("None")),
        )

    def queryset(self, request, queryset):
        kwargs = {
            "%s" % self.parameter_name: None,
        }
        if self.value() == "0":
            return queryset.filter(**kwargs)
        if self.value() == "1":
            return queryset.exclude(**kwargs)
        return queryset


def make_nullfilter(field, title):
    return type(
        str("%sNullFilter" % field.title()),
        (NullFilter,),
        {"title": title, "parameter_name": field},
    )
