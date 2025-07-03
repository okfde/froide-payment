from django.dispatch import Signal

subscription_created = Signal()
subscription_cancel_feedback = Signal()  # args: ['sender', 'data']
subscription_canceled = Signal()
subscription_activated = Signal()
subscription_deactivated = Signal()
sepa_notification = Signal()
