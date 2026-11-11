"""Prometheus gauges for the integrity checks, read from the database at scrape
time.

A task can't report that it didn't run, and nothing inside Django notices if
Celery beat stops. These gauges let an outside alert notice instead, e.g.:

    time() - mm_billing_integrity_last_complete_timestamp_seconds > 129600

Reading at scrape time, rather than pushing from a task, keeps them right
after a restart and whether or not beat is alive.
"""

import logging

from django.db import DatabaseError
from django.db.models import Count
from prometheus_client.core import REGISTRY, GaugeMetricFamily

logger = logging.getLogger("integrity")

LAST_COMPLETE = "mm_billing_integrity_last_complete_timestamp_seconds"
OPEN_ISSUES = "mm_billing_integrity_open_issues"


def _families():
    last_complete = GaugeMetricFamily(
        LAST_COMPLETE,
        "Unix time the last complete billing integrity check finished.",
    )
    open_issues = GaugeMetricFamily(
        OPEN_ISSUES,
        "Open, unacknowledged billing integrity issues.",
        labels=["severity", "source"],
    )
    return last_complete, open_issues


class IntegrityCollector:
    def describe(self):
        # Without describe(), registering would call collect() and query the
        # database while the app registry is still loading.
        return list(_families())

    def collect(self):
        from .store import last_complete_run, open_issues

        last_complete, open_issue_counts = _families()
        try:
            run = last_complete_run()
            counts = (
                open_issues()
                .filter(acknowledged_at__isnull=True)
                .values("severity", "source")
                .annotate(total=Count("pk"))
            )
            counts = list(counts)
        except DatabaseError as error:
            logger.warning(f"Couldn't read integrity metrics: {error}")
            return

        if run is not None and run.finished_at is not None:
            last_complete.add_metric([], run.finished_at.timestamp())
        for row in counts:
            open_issue_counts.add_metric([row["severity"], row["source"]], row["total"])
        yield last_complete
        yield open_issue_counts


_collector = None


def register_collector():
    global _collector
    if _collector is None:
        _collector = IntegrityCollector()
        REGISTRY.register(_collector)
