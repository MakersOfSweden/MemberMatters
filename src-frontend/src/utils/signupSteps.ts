// Shared source of truth for signup steps.
//
// `enabledSignupSteps` is the canonical list of member-facing *requirements*,
// keyed to the backend's `requiredSteps` strings via REQUIRED_STEP_KEY. It
// drives the read-only views (MembershipStatusCard, admin Signup Progress).
//
// The two signup steppers render flows rather than bare requirements, so they
// build their lists from `preSignupSteps` / `postSignupSteps` below, which
// expand the canonical list with the UI-only steps each one needs. Everything
// derives from the same predicates, so the three can't drift.
//
// Build a stepper's list ONCE, after its inputs have loaded, and hold it in a
// data field: q-stepper's v-model is an index into the list, so a list that
// reshapes underneath it silently re-points at a different panel.

export type SignupStep = 'payment' | 'terms' | 'induction' | 'accessCard';

// The pre-payment stepper (SelectTier) expands 'payment' into its own steps.
export type PreSignupStep = 'terms' | 'tier' | 'plan' | 'billing' | 'confirm';

// The post-payment stepper (SignupRequiredSteps) shows 'payment' as a done
// breadcrumb and ends on a terminal confirmation.
export type PostSignupStep =
  'billing' | 'terms' | 'induction' | 'accessCard' | 'confirm';

export interface SignupStepState {
  complete: boolean;
  pending: boolean;
}

interface SignupFeatures {
  enableMembershipPayments?: boolean;
  signup?: {
    termsAcceptanceCards?: unknown[];
    enableInduction?: boolean;
    requireAccessCard?: boolean;
  };
}

// Maps a checklist step to the key the backend reports in `requiredSteps`.
const REQUIRED_STEP_KEY: Record<Exclude<SignupStep, 'payment'>, string> = {
  terms: 'termsAcceptance',
  induction: 'induction',
  accessCard: 'accessCard',
};

const termsConfigured = (features: SignupFeatures) =>
  (features.signup?.termsAcceptanceCards || []).length > 0;
const inductionEnabled = (features: SignupFeatures) =>
  !!features.signup?.enableInduction;
const accessCardRequired = (features: SignupFeatures) =>
  !!features.signup?.requireAccessCard;
const paymentsEnabled = (features: SignupFeatures) =>
  !!features.enableMembershipPayments;
const termsOutstanding = (features: SignupFeatures, outstanding: string[]) =>
  termsConfigured(features) && outstanding.includes(REQUIRED_STEP_KEY.terms);

// Same order as postSignupSteps, which the read-only views mirror.
export function enabledSignupSteps(features: SignupFeatures): SignupStep[] {
  const steps: SignupStep[] = [];
  if (paymentsEnabled(features)) steps.push('payment');
  if (termsConfigured(features)) steps.push('terms');
  if (inductionEnabled(features)) steps.push('induction');
  if (accessCardRequired(features)) steps.push('accessCard');
  return steps;
}

export function preSignupSteps(
  features: SignupFeatures,
  { tierCount, outstanding }: { tierCount: number; outstanding: string[] }
): PreSignupStep[] {
  const steps: PreSignupStep[] = [];
  // Terms come first: the member agrees before picking or paying for
  // anything. Absent once accepted, so a re-signup goes straight to tiers.
  if (termsOutstanding(features, outstanding)) steps.push('terms');
  // Exactly one tier — it gets preselected, so drop the picker. Note `!== 1`
  // rather than `> 1`: with zero tiers the step has to stay, because it is
  // what renders the "no tiers available" empty state.
  if (tierCount !== 1) steps.push('tier');
  steps.push('plan', 'billing', 'confirm');
  return steps;
}

// Every configured step is listed, done or not; the stepper skips past the
// ones the backend no longer requires.
export function postSignupSteps(features: SignupFeatures): PostSignupStep[] {
  // Billing is a breadcrumb: it's already done by the time we get here.
  const steps: PostSignupStep[] = ['billing'];
  if (termsConfigured(features)) steps.push('terms');
  if (inductionEnabled(features)) steps.push('induction');
  if (accessCardRequired(features)) steps.push('accessCard');
  steps.push('confirm');
  return steps;
}

// The next step after `from` that this member actually needs to stop on.
// Returns null when `from` is last or not in the list. `skip` steps over
// anything already satisfied.
export function nextStepAfter<T extends string>(
  steps: T[],
  from: T,
  skip: (step: T) => boolean = () => false
): T | null {
  const start = steps.indexOf(from);
  if (start < 0) return null;
  for (let i = start + 1; i < steps.length; i++) {
    if (!skip(steps[i])) return steps[i];
  }
  return null;
}

export function signupStepStatus(
  step: SignupStep,
  requiredSteps: string[] | null,
  subscriptionState: string | null | undefined
): SignupStepState {
  if (step === 'payment') {
    return {
      complete: subscriptionState === 'active',
      pending: subscriptionState === 'pending',
    };
  }
  const key = REQUIRED_STEP_KEY[step];
  return {
    // requiredSteps === null means "not loaded yet" — treat as incomplete.
    complete: requiredSteps !== null && !requiredSteps.includes(key),
    pending: false,
  };
}

// The one step the member should do next: first that's neither complete nor
// merely pending. null when nothing is actionable (all done or only pending).
export function nextSignupStep(
  features: SignupFeatures,
  requiredSteps: string[] | null,
  subscriptionState: string | null | undefined
): SignupStep | null {
  const next = enabledSignupSteps(features).find((step) => {
    const status = signupStepStatus(step, requiredSteps, subscriptionState);
    return !status.complete && !status.pending;
  });
  return next || null;
}
