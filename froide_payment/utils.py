import csv
from decimal import Decimal

from django.conf import settings
from django.http import StreamingHttpResponse


def get_client_ip(request=None):
    if request is None:
        return None
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[-1].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def get_payment_defaults(order, request=None):
    return {
        'total': order.amount,
        'delivery': Decimal('0.0'),
        'tax': Decimal('0.0'),
        'currency': settings.DEFAULT_CURRENCY,
        'billing_first_name': order.first_name,
        'billing_last_name': order.last_name,
        'billing_address_1': order.street_address_1,
        'billing_address_2': order.street_address_2,
        'billing_city': order.city,
        'billing_postcode': order.postcode,
        'billing_country_code': order.country,
        'billing_email': order.user_email,
        'description': order.description,
        'customer_ip_address': get_client_ip(request)
    }


def dicts_to_csv_response(generator, name='export.csv'):
    response = StreamingHttpResponse(
        dict_to_csv_stream(generator),
        content_type='text/csv'
    )
    response['Content-Disposition'] = 'attachment; filename="%s"' % name
    return response


class FakeFile(object):
    def write(self, string):
        self._last_string = string.encode('utf-8')


def dict_to_csv_stream(stream):
    writer = None
    fake_file = FakeFile()
    for d in stream:
        if writer is None:
            field_names = list(d.keys())
            writer = csv.DictWriter(fake_file, field_names)
            writer.writeheader()
            yield fake_file._last_string
        writer.writerow(d)
        yield fake_file._last_string
