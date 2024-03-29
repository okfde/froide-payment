# -*- coding: utf-8 -*-
# Generated by Django 1.11.15 on 2018-09-24 17:30
from __future__ import unicode_literals

import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import django_countries.fields


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Order",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    models.DateTimeField(
                        default=django.utils.timezone.now, editable=False
                    ),
                ),
                ("first_name", models.CharField(blank=True, max_length=256)),
                ("last_name", models.CharField(blank=True, max_length=256)),
                ("company_name", models.CharField(blank=True, max_length=256)),
                ("street_address_1", models.CharField(blank=True, max_length=256)),
                ("street_address_2", models.CharField(blank=True, max_length=256)),
                ("city", models.CharField(blank=True, max_length=256)),
                ("postcode", models.CharField(blank=True, max_length=20)),
                ("country", django_countries.fields.CountryField(max_length=2)),
                (
                    "user_email",
                    models.EmailField(blank=True, default="", max_length=254),
                ),
                (
                    "total_net",
                    models.DecimalField(decimal_places=2, default=0, max_digits=12),
                ),
                (
                    "total_gross",
                    models.DecimalField(decimal_places=2, default=0, max_digits=12),
                ),
                ("description", models.CharField(blank=True, max_length=255)),
                ("customer_note", models.TextField(blank=True, default="")),
                ("token", models.UUIDField(db_index=True, default=uuid.uuid4)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="invoices",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Payment",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("variant", models.CharField(max_length=255)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("waiting", "Waiting for confirmation"),
                            ("preauth", "Pre-authorized"),
                            ("confirmed", "Confirmed"),
                            ("rejected", "Rejected"),
                            ("refunded", "Refunded"),
                            ("error", "Error"),
                            ("input", "Input"),
                        ],
                        default="waiting",
                        max_length=10,
                    ),
                ),
                (
                    "fraud_status",
                    models.CharField(
                        choices=[
                            ("unknown", "Unknown"),
                            ("accept", "Passed"),
                            ("reject", "Rejected"),
                            ("review", "Review"),
                        ],
                        default="unknown",
                        max_length=10,
                        verbose_name="fraud check",
                    ),
                ),
                ("fraud_message", models.TextField(blank=True, default="")),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("modified", models.DateTimeField(auto_now=True)),
                ("transaction_id", models.CharField(blank=True, max_length=255)),
                ("currency", models.CharField(max_length=10)),
                (
                    "total",
                    models.DecimalField(decimal_places=2, default="0.0", max_digits=9),
                ),
                (
                    "delivery",
                    models.DecimalField(decimal_places=2, default="0.0", max_digits=9),
                ),
                (
                    "tax",
                    models.DecimalField(decimal_places=2, default="0.0", max_digits=9),
                ),
                ("description", models.TextField(blank=True, default="")),
                ("billing_first_name", models.CharField(blank=True, max_length=256)),
                ("billing_last_name", models.CharField(blank=True, max_length=256)),
                ("billing_address_1", models.CharField(blank=True, max_length=256)),
                ("billing_address_2", models.CharField(blank=True, max_length=256)),
                ("billing_city", models.CharField(blank=True, max_length=256)),
                ("billing_postcode", models.CharField(blank=True, max_length=256)),
                ("billing_country_code", models.CharField(blank=True, max_length=2)),
                ("billing_country_area", models.CharField(blank=True, max_length=256)),
                ("billing_email", models.EmailField(blank=True, max_length=254)),
                (
                    "customer_ip_address",
                    models.GenericIPAddressField(blank=True, null=True),
                ),
                ("extra_data", models.TextField(blank=True, default="")),
                ("message", models.TextField(blank=True, default="")),
                ("token", models.CharField(blank=True, default="", max_length=36)),
                (
                    "captured_amount",
                    models.DecimalField(decimal_places=2, default="0.0", max_digits=9),
                ),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payments",
                        to="froide_payment.Order",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
    ]
