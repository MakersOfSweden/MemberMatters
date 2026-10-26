// The i18n keys to show when saving a profile fails.
//
// A 409 carries one key as `message`. A 400 from the field checks carries
// `{ field: [key, ...] }`, the shape DRF gives serializer errors (see
// memberportal/profile/profile_changes.py). Keys are de-duplicated. Anything
// else gives [], for the caller to show its generic error instead.
export function errorKeys(response?: {
  status?: number;
  data?: unknown;
}): string[] {
  if (response?.status !== 400 && response?.status !== 409) return [];

  const data = response.data;
  if (!data || typeof data !== 'object') return [];

  const { message } = data as { message?: unknown };
  if (typeof message === 'string') return [message];

  const keys = Object.values(data as Record<string, unknown>)
    .flat()
    .filter((key): key is string => typeof key === 'string');
  return [...new Set(keys)];
}
