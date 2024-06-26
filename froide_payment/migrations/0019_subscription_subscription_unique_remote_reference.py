# Generated by Django 4.2.4 on 2024-04-26 09:57

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("froide_payment", "0018_order_remote_reference_is_unique_and_more"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="subscription",
            constraint=models.UniqueConstraint(
                models.F("remote_reference"),
                condition=models.Q(("remote_reference", ""), _negated=True),
                name="subscription_unique_remote_reference",
            ),
        ),
    ]
