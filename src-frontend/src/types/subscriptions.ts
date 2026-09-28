import { z } from 'zod';

export const SubscriptionStateSchema = z.enum([
  'inactive',
  'active',
  'cancelling',
  'pending',
]);
export type SubscriptionState = z.infer<typeof SubscriptionStateSchema>;

export const MemberPlanSchema = z.object({
  id: z.number(),
  name: z.string(),
  currency: z.string(),
  cost: z.number(),
  intervalAmount: z.number(),
  interval: z.string(),
});

export type MemberPlan = z.infer<typeof MemberPlanSchema>;

export const MemberTierSchema = z.object({
  id: z.number(),
  name: z.string(),
  description: z.string(),
  featured: z.boolean(),
  plans: z.array(MemberPlanSchema),
});

export type MemberTier = z.infer<typeof MemberTierSchema>;

// Dates are ISO 8601 UTC strings, e.g. "2026-09-24T08:15:00.000Z".
export const MemberSubscriptionSchema = z.object({
  billingCycleAnchor: z.string(),
  cancelAt: z.string().nullable(),
  cancelAtPeriodEnd: z.boolean(),
  currentPeriodEnd: z.string(),
  startDate: z.string(),
  status: z.string(),
  billingMethod: z.string().optional(),
  collectionMethod: z.string().nullable().optional(),
  invoiceUrl: z.string().nullable().optional(),
  membershipPlan: MemberPlanSchema,
  membershipTier: MemberTierSchema,
});

export type MemberSubscription = z.infer<typeof MemberSubscriptionSchema>;
