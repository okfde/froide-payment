# Generated by Django 4.2.4 on 2024-02-20 16:54

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("froide_payment", "0017_order_unique_remote_reference_service_start"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="remote_reference_is_unique",
            field=models.BooleanField(default=False),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.UniqueConstraint(
                models.F("remote_reference"),
                condition=models.Q(("remote_reference_is_unique", True)),
                name="unique_remote_reference",
            ),
        ),
        migrations.AddConstraint(
            model_name="payment",
            constraint=models.UniqueConstraint(
                models.F("transaction_id"),
                condition=models.Q(("transaction_id", ""), _negated=True),
                name="unique_transaction_id",
            ),
        ),
    ]
