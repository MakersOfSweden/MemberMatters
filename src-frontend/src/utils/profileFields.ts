// The profile fields and their PROFILE_FIELD_* settings, as the forms use them.
//
// The rules mirror memberportal/profile/profile_changes.py, which applies them
// on the server; the forms only use them to show the right inputs.

export type FieldMode =
  | 'hidden'
  | 'optional'
  | 'optional_admin_edits'
  | 'required'
  | 'required_admin_edits';

export type ProfileFieldKey =
  | 'email'
  | 'firstName'
  | 'lastName'
  | 'phone'
  | 'screenName'
  | 'vehicleRegistrationPlate'
  | 'address';

// Who is filling in the form.
export type Actor = 'signup' | 'member' | 'admin';

export type Address = Partial<
  Record<'line1' | 'line2' | 'postal_code' | 'city' | 'country', string>
>;

// The values the profile forms hold, keyed as the API names them.
export interface ProfileFieldValues {
  email: string;
  firstName: string;
  lastName: string;
  phone: string;
  screenName: string;
  vehicleRegistrationPlate: string;
  address: Address;
}

export function emptyProfileFields(): ProfileFieldValues {
  return {
    email: '',
    firstName: '',
    lastName: '',
    phone: '',
    screenName: '',
    vehicleRegistrationPlate: '',
    address: {},
  };
}

export interface AddressPart {
  key: keyof Address;
  required: boolean;
  maxLength: number;
}

// The settings' defaults in memberportal/membermatters/constance_config.py,
// used when the site config doesn't say.
export const DEFAULT_FIELD_MODES: Record<ProfileFieldKey, FieldMode> = {
  email: 'required',
  firstName: 'required',
  lastName: 'required',
  phone: 'required',
  screenName: 'required',
  vehicleRegistrationPlate: 'hidden',
  address: 'hidden',
};

// ADDRESS_PARTS in memberportal/profile/profile_fields.py, used when the site
// config doesn't say.
export const DEFAULT_ADDRESS_PARTS: AddressPart[] = [
  { key: 'line1', required: true, maxLength: 200 },
  { key: 'line2', required: false, maxLength: 200 },
  { key: 'postal_code', required: true, maxLength: 20 },
  { key: 'city', required: true, maxLength: 100 },
  { key: 'country', required: true, maxLength: 2 },
];

interface ProfileFieldFeatures {
  profileFields?: Partial<Record<string, string>>;
  addressParts?: AddressPart[];
}

const MODES: FieldMode[] = [
  'hidden',
  'optional',
  'optional_admin_edits',
  'required',
  'required_admin_edits',
];

export function fieldMode(
  features: ProfileFieldFeatures | undefined,
  key: ProfileFieldKey
): FieldMode {
  const mode = features?.profileFields?.[key];
  return MODES.includes(mode as FieldMode)
    ? (mode as FieldMode)
    : DEFAULT_FIELD_MODES[key];
}

export function addressParts(
  features: ProfileFieldFeatures | undefined
): AddressPart[] {
  return features?.addressParts?.length
    ? features.addressParts
    : DEFAULT_ADDRESS_PARTS;
}

export function isRequired(mode: FieldMode): boolean {
  return mode === 'required' || mode === 'required_admin_edits';
}

export function onlyAdminsEdit(mode: FieldMode): boolean {
  return mode === 'optional_admin_edits' || mode === 'required_admin_edits';
}

export function isBlank(value: unknown): boolean {
  if (value === null || value === undefined || value === '') return true;
  if (typeof value === 'object') {
    return Object.values(value as object).every((part) => isBlank(part));
  }
  return false;
}

// Whether the field is shown. A hidden field is shown only to admins, and
// only when something is stored, read-only.
export function isShown(
  mode: FieldMode,
  actor: Actor,
  stored: unknown
): boolean {
  return mode !== 'hidden' || (actor === 'admin' && !isBlank(stored));
}

// Whether `actor` can change the field, given its stored value. A member may
// fill in an "only admins edit" field once, while it is empty.
export function canEdit(
  mode: FieldMode,
  actor: Actor,
  stored: unknown
): boolean {
  if (mode === 'hidden') return false;
  if (actor === 'member' && onlyAdminsEdit(mode)) return isBlank(stored);
  return true;
}
