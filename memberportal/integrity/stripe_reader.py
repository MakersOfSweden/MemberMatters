"""Read-only, rate-limited access to the Stripe API for the integrity checks.

Stripe allows 100 requests a second in live mode and 25 in a sandbox, shared
with webhooks, signups and everything else the site does, and asks background
jobs to use only part of that. Every request a run makes goes through one
StripeReader, which spaces requests out, backs off on 429s and stops the run
at a hard cap, so a paging bug can't loop against the API.

Paging is done here rather than with auto_paging_iter(), whose follow-up
requests would bypass the throttle.
"""

import random
import time

import stripe

# More than a full run needs on any realistic install: about one request per
# 100 live subscriptions, one per plan and a handful more.
MAX_REQUESTS_PER_RUN = 1000

# Waits before each retry after a 429 or a dropped connection: 1, 2, 4, 8s.
MAX_RETRIES = 4

PAGE_SIZE = 100


class StripeBudgetExceeded(Exception):
    """The run used up its request budget."""


class Throttle:
    """Spaces calls at least 1/rate seconds apart."""

    def __init__(self, rate, clock=time.monotonic, sleep=time.sleep):
        self.interval = 1 / max(rate, 0.1)
        self.clock = clock
        self.sleep = sleep
        self._next = None

    def wait(self):
        now = self.clock()
        if self._next is not None and now < self._next:
            self.sleep(self._next - now)
            now = self._next
        self._next = now + self.interval


class StripeReader:
    def __init__(
        self,
        rate,
        max_requests=MAX_REQUESTS_PER_RUN,
        max_retries=MAX_RETRIES,
        clock=time.monotonic,
        sleep=time.sleep,
        jitter=random.random,
    ):
        self.throttle = Throttle(rate, clock=clock, sleep=sleep)
        self.max_requests = max_requests
        self.max_retries = max_retries
        self.sleep = sleep
        self.jitter = jitter
        self.requests = 0

    def call(self, method, *args, **kwargs):
        """Call one Stripe API method, retrying 429s and connection errors."""
        attempt = 0
        while True:
            if self.requests >= self.max_requests:
                raise StripeBudgetExceeded(
                    f"stopped after {self.requests} Stripe requests"
                )
            self.throttle.wait()
            self.requests += 1
            try:
                return method(*args, **kwargs)
            except (stripe.error.RateLimitError, stripe.error.APIConnectionError):
                if attempt >= self.max_retries:
                    raise
                self.sleep(2**attempt + self.jitter() / 2)
                attempt += 1

    def list_all(self, method, **params):
        """Every object of a list endpoint, one throttled request per page."""
        params = {"limit": PAGE_SIZE, **params}
        page = self.call(method, **params)
        while True:
            data = page["data"]
            yield from data
            if not page.get("has_more") or not data:
                return
            page = self.call(method, **params, starting_after=data[-1]["id"])
