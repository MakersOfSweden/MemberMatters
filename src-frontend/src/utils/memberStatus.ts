// Badge colours for a member's state and subscription status, shared by the
// admin member lists and their cards.

const STATE_COLORS: Record<string, string> = {
  active: 'positive',
  noob: 'orange',
  inactive: 'yellow-8',
  accountonly: 'blue-grey',
};

const SUBSCRIPTION_COLORS: Record<string, string> = {
  active: 'positive',
  pending: 'warning',
  cancelling: 'deep-orange',
  inactive: 'grey-6',
};

export function memberStateColor(state: string | null | undefined): string {
  return (state && STATE_COLORS[state]) || 'grey-7';
}

export function subscriptionStatusColor(
  status: string | null | undefined
): string {
  return (status && SUBSCRIPTION_COLORS[status]) || 'grey-6';
}
