"""The rate limiter that keeps the billing check well under Stripe's limits."""

import pytest
import stripe

from integrity.stripe_reader import StripeBudgetExceeded, StripeReader, Throttle


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(round(seconds, 3))
        self.now += seconds


def reader(clock, **kwargs):
    return StripeReader(
        rate=kwargs.pop("rate", 5),
        clock=clock,
        sleep=clock.sleep,
        jitter=lambda: 0,
        **kwargs,
    )


class TestThrottle:
    def test_spaces_calls_at_the_rate(self):
        clock = FakeClock()
        throttle = Throttle(5, clock=clock, sleep=clock.sleep)

        for _ in range(4):
            throttle.wait()

        assert clock.sleeps == [0.2, 0.2, 0.2]

    def test_doesnt_wait_when_calls_are_already_far_apart(self):
        clock = FakeClock()
        throttle = Throttle(5, clock=clock, sleep=clock.sleep)

        throttle.wait()
        clock.now += 1
        throttle.wait()

        assert clock.sleeps == []


class TestCall:
    def test_backs_off_on_429_and_retries(self):
        clock = FakeClock()
        responses = [stripe.error.RateLimitError("slow down")] * 2 + ["ok"]

        def method():
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        stripe_reader = reader(clock, rate=1000)

        assert stripe_reader.call(method) == "ok"
        assert [s for s in clock.sleeps if s >= 1] == [1, 2]
        assert stripe_reader.requests == 3

    def test_gives_up_after_the_last_retry(self):
        clock = FakeClock()

        def method():
            raise stripe.error.RateLimitError("slow down")

        with pytest.raises(stripe.error.RateLimitError):
            reader(clock, rate=1000).call(method)
        assert [s for s in clock.sleeps if s >= 1] == [1, 2, 4, 8]

    def test_doesnt_retry_other_errors(self):
        calls = []

        def method():
            calls.append(1)
            raise stripe.error.AuthenticationError("bad key")

        with pytest.raises(stripe.error.AuthenticationError):
            reader(FakeClock()).call(method)
        assert len(calls) == 1

    def test_stops_at_the_request_budget(self):
        stripe_reader = reader(FakeClock(), rate=1000, max_requests=3)

        for _ in range(3):
            stripe_reader.call(lambda: None)
        with pytest.raises(StripeBudgetExceeded):
            stripe_reader.call(lambda: None)


def test_list_all_pages_through_the_throttle():
    pages = {
        None: {"data": [{"id": "a"}, {"id": "b"}], "has_more": True},
        "b": {"data": [{"id": "c"}], "has_more": False},
    }
    calls = []

    def method(**params):
        calls.append(params)
        return pages[params.get("starting_after")]

    stripe_reader = reader(FakeClock(), rate=1000)

    ids = [obj["id"] for obj in stripe_reader.list_all(method, status="active")]

    assert ids == ["a", "b", "c"]
    assert calls == [
        {"limit": 100, "status": "active"},
        {"limit": 100, "status": "active", "starting_after": "b"},
    ]
    assert stripe_reader.requests == 2
