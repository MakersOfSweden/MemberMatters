import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { describe, it, expect } from 'vitest';
import {
  DEFAULT_ADDRESS_PARTS,
  DEFAULT_FIELD_MODES,
  addressParts,
  canEdit,
  fieldMode,
  isBlank,
  isShown,
  type FieldMode,
} from './profileFields';

function backendFile(path: string): string {
  return readFileSync(
    fileURLToPath(new URL(`../../../memberportal/${path}`, import.meta.url)),
    'utf8'
  );
}

describe('the defaults', () => {
  it('match the settings defaults in the backend', () => {
    const config = backendFile('membermatters/constance_config.py');
    const defaults = Object.fromEntries(
      [...config.matchAll(/"PROFILE_FIELD_(\w+)": \(\s*(\w+),/g)].map(
        ([, setting, constant]) => [setting, constant.toLowerCase()]
      )
    );

    expect(DEFAULT_FIELD_MODES).toEqual({
      email: defaults.EMAIL,
      firstName: defaults.NAME,
      lastName: defaults.NAME,
      phone: defaults.PHONE,
      screenName: defaults.SCREEN_NAME,
      vehicleRegistrationPlate: defaults.VEHICLE_PLATE,
      address: defaults.ADDRESS,
    });
  });

  it('list the address parts the backend has', () => {
    const fields = backendFile('profile/profile_fields.py');
    const parts = [
      ...fields.matchAll(
        /AddressPart\("(\w+)", (\d+), required=(True|False)\)/g
      ),
    ].map(([, key, maxLength, required]) => ({
      key,
      required: required === 'True',
      maxLength: Number(maxLength),
    }));

    expect(DEFAULT_ADDRESS_PARTS).toEqual(parts);
  });
});

describe('fieldMode', () => {
  it('reads the site config', () => {
    const features = { profileFields: { phone: 'optional_admin_edits' } };

    expect(fieldMode(features, 'phone')).toBe('optional_admin_edits');
  });

  it('falls back to the default for a missing or unknown value', () => {
    expect(fieldMode(undefined, 'vehicleRegistrationPlate')).toBe('hidden');
    expect(fieldMode({ profileFields: { phone: 'nonsense' } }, 'phone')).toBe(
      'required'
    );
  });
});

describe('addressParts', () => {
  it('reads the site config, or falls back to the defaults', () => {
    const parts = [{ key: 'city' as const, required: true, maxLength: 10 }];

    expect(addressParts({ addressParts: parts })).toEqual(parts);
    expect(addressParts({})).toEqual(DEFAULT_ADDRESS_PARTS);
  });
});

describe('isBlank', () => {
  it('treats empty values and addresses with nothing filled in as blank', () => {
    expect(isBlank(null)).toBe(true);
    expect(isBlank('')).toBe(true);
    expect(isBlank({})).toBe(true);
    expect(isBlank({ line1: '', city: '' })).toBe(true);
    expect(isBlank({ city: 'Stockholm' })).toBe(false);
    expect(isBlank('ada')).toBe(false);
  });
});

describe('isShown', () => {
  it('hides a hidden field, except from admins while a value is stored', () => {
    expect(isShown('hidden', 'member', 'ABC123')).toBe(false);
    expect(isShown('hidden', 'signup', '')).toBe(false);
    expect(isShown('hidden', 'admin', '')).toBe(false);
    expect(isShown('hidden', 'admin', 'ABC123')).toBe(true);
    expect(isShown('optional', 'member', '')).toBe(true);
  });
});

describe('canEdit', () => {
  // The rules table in memberportal/profile/profile_changes.py.
  const cases: [FieldMode, string, boolean, boolean, boolean][] = [
    // mode, stored, signup, member, admin
    ['hidden', 'x', false, false, false],
    ['optional', 'x', true, true, true],
    ['optional_admin_edits', '', true, true, true],
    ['optional_admin_edits', 'x', true, false, true],
    ['required', 'x', true, true, true],
    ['required_admin_edits', '', true, true, true],
    ['required_admin_edits', 'x', true, false, true],
  ];

  it.each(cases)('%s with %j stored', (mode, stored, signup, member, admin) => {
    expect(canEdit(mode, 'signup', stored)).toBe(signup);
    expect(canEdit(mode, 'member', stored)).toBe(member);
    expect(canEdit(mode, 'admin', stored)).toBe(admin);
  });
});
