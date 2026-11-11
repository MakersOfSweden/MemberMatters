import stripe
from django.apps import AppConfig
from django.conf import settings


class ApiBillingConfig(AppConfig):
    name = "api_billing"

    def ready(self):
        # Every process that loads Django (web, Celery, management commands)
        # sends the same pinned version with its Stripe requests.
        stripe.api_version = settings.STRIPE_API_VERSION
