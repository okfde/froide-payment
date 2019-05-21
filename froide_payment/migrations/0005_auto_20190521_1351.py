# Generated by Django 2.2 on 2019-05-21 11:51

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import django_countries.fields
import django_prices.models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('froide_payment', '0004_auto_20190416_1719'),
    ]

    operations = [
        migrations.CreateModel(
            name='Customer',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('first_name', models.CharField(blank=True, max_length=256)),
                ('last_name', models.CharField(blank=True, max_length=256)),
                ('company_name', models.CharField(blank=True, max_length=256)),
                ('street_address_1', models.CharField(blank=True, max_length=256)),
                ('street_address_2', models.CharField(blank=True, max_length=256)),
                ('city', models.CharField(blank=True, max_length=256)),
                ('postcode', models.CharField(blank=True, max_length=20)),
                ('country', django_countries.fields.CountryField(max_length=2)),
                ('user_email', models.EmailField(blank=True, default='', max_length=254)),
                ('remote_reference', models.CharField(blank=True, max_length=256)),
                ('custom_data', models.TextField()),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='Plan',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=256)),
                ('slug', models.SlugField()),
                ('category', models.CharField(blank=True, max_length=256)),
                ('description', models.TextField(blank=True)),
                ('created', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('amount', django_prices.models.MoneyField(currency='EUR', decimal_places=2, default=0, max_digits=12)),
                ('interval', models.PositiveSmallIntegerField(blank=True, choices=[(1, 'monthly'), (3, 'quarterly'), (6, 'semiannually'), (12, 'annually')], null=True, verbose_name='Montly interval')),
                ('remote_reference', models.CharField(blank=True, max_length=256)),
            ],
        ),
        migrations.AlterModelOptions(
            name='payment',
            options={'ordering': ('-modified',)},
        ),
        migrations.CreateModel(
            name='Subscription',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('active', models.BooleanField(default=False)),
                ('created', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('last_date', models.DateTimeField(blank=True, null=True)),
                ('next_date', models.DateTimeField(blank=True, null=True)),
                ('remote_reference', models.CharField(blank=True, max_length=256)),
                ('token', models.UUIDField(db_index=True, default=uuid.uuid4)),
                ('customer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='froide_payment.Customer')),
                ('plan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='froide_payment.Plan')),
            ],
        ),
        migrations.AddField(
            model_name='order',
            name='customer',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='froide_payment.Customer'),
        ),
        migrations.AddField(
            model_name='order',
            name='subscription',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='froide_payment.Subscription'),
        ),
    ]
