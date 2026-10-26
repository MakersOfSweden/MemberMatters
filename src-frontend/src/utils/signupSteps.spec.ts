import { describe, expect, it } from 'vitest';
import { matchesStepFilters, signupStepState } from './signupSteps';

const allFeatures = {
  enableMembershipPayments: true,
  signup: {
    termsAcceptanceCards: [{}],
    enableInduction: true,
    requireAccessCard: true,
  },
};

describe('signupStepState', () => {
  it('maps the subscription status for payment', () => {
    expect(signupStepState('payment', [], 'active')).toBe('complete');
    expect(signupStepState('payment', [], 'pending')).toBe('pending');
    expect(signupStepState('payment', [], 'inactive')).toBe('outstanding');
    expect(signupStepState('payment', [], 'cancelling')).toBe('outstanding');
  });

  it('is complete once the backend no longer requires the step', () => {
    const required = ['termsAcceptance', 'accessCard'];
    expect(signupStepState('terms', required, 'active')).toBe('outstanding');
    expect(signupStepState('induction', required, 'active')).toBe('complete');
    expect(signupStepState('accessCard', required, 'active')).toBe(
      'outstanding'
    );
  });

  it('treats unloaded requiredSteps as outstanding', () => {
    expect(signupStepState('induction', null, 'active')).toBe('outstanding');
  });
});

describe('matchesStepFilters', () => {
  const paidNotInducted = { required: ['induction'], sub: 'active' };
  const unpaid = { required: ['induction', 'accessCard'], sub: 'inactive' };
  const invoiced = { required: ['induction'], sub: 'pending' };

  const matches = (
    filters: Parameters<typeof matchesStepFilters>[1],
    row: { required: string[]; sub: string },
    features = allFeatures
  ) => matchesStepFilters(features, filters, row.required, row.sub);

  it('matches everyone with no filters', () => {
    expect(matches({}, paidNotInducted)).toBe(true);
    expect(matches({}, unpaid)).toBe(true);
  });

  it('ANDs filters across steps', () => {
    const filters = {
      payment: 'complete',
      induction: 'outstanding',
    } as const;
    expect(matches(filters, paidNotInducted)).toBe(true);
    expect(matches(filters, unpaid)).toBe(false);
    expect(matches(filters, invoiced)).toBe(false);
  });

  it('only matches pending payments on pending', () => {
    expect(matches({ payment: 'pending' }, invoiced)).toBe(true);
    expect(matches({ payment: 'pending' }, unpaid)).toBe(false);
    expect(matches({ payment: 'outstanding' }, invoiced)).toBe(false);
  });

  it('ignores filters on steps that are not enabled', () => {
    const noInduction = {
      ...allFeatures,
      signup: { ...allFeatures.signup, enableInduction: false },
    };
    expect(matches({ induction: 'complete' }, unpaid, noInduction)).toBe(true);
  });
});
