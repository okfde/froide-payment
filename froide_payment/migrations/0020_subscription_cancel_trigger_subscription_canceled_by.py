# Generated by Django 5.1.1 on 2025-07-03 11:17

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("froide_payment", "0019_subscription_subscription_unique_remote_reference"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="cancel_trigger",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="subscription",
            name="canceled_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
