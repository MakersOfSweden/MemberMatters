import { describe, it, expect } from 'vitest';
import {
  apiMessage,
  bannerText,
  compareIssues,
  issueEvents,
  runFinished,
  runStatusLabel,
  scheduleText,
  seenIn,
  severityColor,
  severityLabel,
  textColorOn,
  skippedReasons,
  statusBanners,
} from './billingIntegrity';
import type {
  IntegrityIssue,
  IntegrityRun,
  IntegrityStatus,
} from '../types/billingIntegrity';

const run = (extra: Partial<IntegrityRun> = {}): IntegrityRun => ({
  id: 1,
  startedAt: '2026-10-21T01:15:00.000Z',
  finishedAt: '2026-10-21T01:15:04.000Z',
  status: 'complete',
  trigger: 'schedule',
  stripeRequests: 8,
  membersChecked: 120,
  newIssues: 0,
  resolvedIssues: 0,
  openIssues: 0,
  skippedChecks: [],
  error: '',
  ...extra,
});

const status = (extra: Partial<IntegrityStatus> = {}): IntegrityStatus => ({
  enabled: true,
  celeryConfigured: true,
  running: false,
  schedule: {
    dailyCheckAt: '03:15',
    weeklyDigestDay: 'mon',
    weeklyDigestAt: '08:15',
    timeZone: 'Europe/Stockholm',
  },
  nextRun: '2026-10-22T01:15:00.000Z',
  lastRun: run(),
  lastCompleteRun: run(),
  stale: false,
  counts: { critical: 0, warning: 0, info: 0, acknowledged: 0 },
  sources: [],
  stripeTestMode: false,
  ...extra,
});

const issue = (extra: Partial<IntegrityIssue>): IntegrityIssue => ({
  id: 1,
  check: 'ended_in_stripe',
  severity: 'critical',
  source: 'legacy',
  message: '',
  mm: '',
  stripe: '',
  cause: '',
  action: '',
  extra: {},
  memberId: null,
  memberName: null,
  stripeRef: '',
  stripeUrl: null,
  firstSeen: '2026-10-01T00:00:00.000Z',
  lastSeen: '2026-10-21T00:00:00.000Z',
  occurrences: 1,
  resolvedAt: null,
  acknowledged: false,
  acknowledgedBy: null,
  acknowledgedAt: null,
  notes: '',
  ...extra,
});

describe('statusBanners', () => {
  it('shows nothing when the last run completed on schedule', () => {
    expect(statusBanners(status())).toEqual([]);
  });

  it('shows only that the check is off when it is', () => {
    expect(
      statusBanners(status({ enabled: false, celeryConfigured: false }))
    ).toEqual(['disabled']);
  });

  it('warns about a missing Celery, a stale check and a failed run', () => {
    expect(
      statusBanners(
        status({
          celeryConfigured: false,
          stale: true,
          lastRun: run({ status: 'failed' }),
        })
      )
    ).toEqual(['noCelery', 'stale', 'lastRunFailed']);
  });

  it('warns about an incomplete run', () => {
    expect(
      statusBanners(status({ lastRun: run({ status: 'incomplete' }) }))
    ).toEqual(['lastRunIncomplete']);
  });
});

describe('compareIssues', () => {
  it('puts the most severe first, then the oldest', () => {
    const issues = [
      issue({ id: 1, severity: 'info' }),
      issue({ id: 2, severity: 'critical', firstSeen: '2026-10-20' }),
      issue({ id: 3, severity: 'warning' }),
      issue({ id: 4, severity: 'critical', firstSeen: '2026-10-02' }),
    ];

    expect(issues.sort(compareIssues).map((i) => i.id)).toEqual([4, 2, 3, 1]);
  });
});

describe('severityColor', () => {
  it('uses the Quasar brand colors', () => {
    expect(severityColor('critical')).toBe('negative');
    expect(severityColor('warning')).toBe('warning');
    expect(severityColor('info')).toBe('info');
  });
});

describe('skippedReasons', () => {
  it('lists each reason once', () => {
    const skipped = run({
      skippedChecks: [
        {
          check: 'plan_price',
          source: 'account',
          reason: 'Stripe error: down',
        },
        { check: 'webhook_endpoint', source: 'account', reason: '' },
        {
          check: 'undelivered_events',
          source: 'account',
          reason: 'Stripe error: down',
        },
      ],
    });

    expect(skippedReasons(skipped)).toBe('Stripe error: down');
  });

  it('is empty without a run', () => {
    expect(skippedReasons(null)).toBe('');
  });
});

describe('labels', () => {
  it('names severities and run results', () => {
    expect(severityLabel('critical')).toBe('Critical');
    expect(severityLabel('info')).toBe('Info');
    expect(runStatusLabel('incomplete')).toBe('Incomplete');
  });

  it('counts runs in the singular and plural', () => {
    expect(seenIn(1)).toBe('seen in 1 run');
    expect(seenIn(3)).toBe('seen in 3 runs');
  });
});

describe('scheduleText', () => {
  it('says when the check and the digest run', () => {
    expect(scheduleText(status().schedule)).toBe(
      'The check runs every night at 03:15, and a digest goes to the admin ' +
        'email on Mondays at 08:15 (Europe/Stockholm).'
    );
  });
});

describe('bannerText', () => {
  it('quotes the error of a failed run', () => {
    expect(
      bannerText('lastRunFailed', run({ status: 'failed', error: 'bad key' }))
    ).toBe('The last check failed: bad key');
  });

  it('lists why an incomplete run skipped checks', () => {
    const incomplete = run({
      status: 'incomplete',
      skippedChecks: [
        { check: 'plan_price', source: 'account', reason: 'down' },
      ],
    });

    expect(bannerText('lastRunIncomplete', incomplete)).toBe(
      'The last check skipped some checks: down'
    );
  });
});

describe('apiMessage', () => {
  it('explains a known error code', () => {
    expect(apiMessage('billingIntegrity.alreadyRunning', 'fallback')).toBe(
      'A check is already running.'
    );
  });

  it('falls back for anything else', () => {
    expect(apiMessage(undefined, 'fallback')).toBe('fallback');
    expect(apiMessage('billing.other', 'fallback')).toBe('fallback');
  });
});

describe('issueEvents', () => {
  it('lists the events an undelivered-events issue carries', () => {
    const events = [
      { id: 'evt_1', type: 'invoice.paid', customer: 'cus_1' },
      { id: 'evt_2', type: 'customer.subscription.deleted', customer: null },
    ];

    expect(issueEvents(issue({ extra: { events } }))).toEqual(events);
  });

  it('is empty for other issues', () => {
    expect(issueEvents(issue({ extra: { differences: ['amount'] } }))).toEqual(
      []
    );
  });
});

describe('runFinished', () => {
  it('waits until the queued run has started', () => {
    expect(runFinished(1, status({ lastRun: run({ id: 1 }) }))).toBe(false);
  });

  it('waits while the queued run is running', () => {
    expect(
      runFinished(1, status({ lastRun: run({ id: 2, status: 'running' }) }))
    ).toBe(false);
  });

  it('is done once a newer run has finished', () => {
    expect(
      runFinished(1, status({ lastRun: run({ id: 2, status: 'failed' }) }))
    ).toBe(true);
  });

  it('counts the first run ever', () => {
    expect(runFinished(null, status({ lastRun: run({ id: 1 }) }))).toBe(true);
  });
});

describe('textColorOn', () => {
  it('puts dark text on the light colors and white on the rest', () => {
    expect(textColorOn('warning')).toBe('dark');
    expect(textColorOn('info')).toBe('dark');
    expect(textColorOn('negative')).toBe('white');
    expect(textColorOn('positive')).toBe('white');
  });
});
