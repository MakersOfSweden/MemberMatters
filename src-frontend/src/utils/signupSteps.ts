// Shared source of truth for the signup checklist: which steps apply (from
// site config) and each step's status for a given member. Used by the member
// dashboard card (MembershipStatusCard) and the admin Signup Progress table so
// the two never drift.

export type SignupStep = 'payment' | 'terms' | 'induction' | 'accessCard';

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

// Order here = display order.
export function enabledSignupSteps(features: SignupFeatures): SignupStep[] {
  const steps: SignupStep[] = [];
  if (features.enableMembershipPayments) steps.push('payment');
  if ((features.signup?.termsAcceptanceCards || []).length > 0)
    steps.push('terms');
  if (features.signup?.enableInduction) steps.push('induction');
  if (features.signup?.requireAccessCard) steps.push('accessCard');
  return steps;
}

// Maps a checklist step to the key the backend reports in `requiredSteps`.
const REQUIRED_STEP_KEY: Record<Exclude<SignupStep, 'payment'>, string> = {
  terms: 'termsAcceptance',
  induction: 'induction',
  accessCard: 'accessCard',
};

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
