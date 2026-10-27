// The billing integrity check's API, under /api/admin/billing/integrity/.

export type Severity = 'critical' | 'warning' | 'info';

export type RunStatus = 'running' | 'complete' | 'incomplete' | 'failed';

export interface SkippedCheck {
  check: string;
  source: string;
  reason: string;
}

export interface IntegrityRun {
  id: number;
  startedAt: string;
  finishedAt: string | null;
  status: RunStatus;
  trigger: 'schedule' | 'manual' | 'command' | 'member';
  stripeRequests: number;
  membersChecked: number;
  newIssues: number;
  resolvedIssues: number;
  openIssues: number;
  skippedChecks: SkippedCheck[];
  error: string;
}

export interface IntegrityIssue {
  id: number;
  check: string;
  severity: Severity;
  source: string;
  message: string;
  // What each side says, the likely cause and what to do next.
  mm: string;
  stripe: string;
  cause: string;
  action: string;
  extra: Record<string, unknown>;
  memberId: number | null;
  memberName: string | null;
  stripeRef: string;
  stripeUrl: string | null;
  firstSeen: string;
  lastSeen: string;
  occurrences: number;
  resolvedAt: string | null;
  acknowledged: boolean;
  acknowledgedBy: string | null;
  acknowledgedAt: string | null;
  notes: string;
}

export interface IntegritySchedule {
  dailyCheckAt: string;
  weeklyDigestDay: string;
  weeklyDigestAt: string;
  timeZone: string;
}

export interface IntegrityStatus {
  enabled: boolean;
  celeryConfigured: boolean;
  running: boolean;
  schedule: IntegritySchedule;
  nextRun: string | null;
  lastRun: IntegrityRun | null;
  lastCompleteRun: IntegrityRun | null;
  stale: boolean;
  counts: Record<Severity | 'acknowledged', number>;
  sources: { value: string; label: string }[];
  stripeTestMode: boolean;
}
