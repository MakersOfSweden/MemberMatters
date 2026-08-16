import { describe, it, expect } from 'vitest';
import {
  normalizeSearchText,
  fuzzyTokenMatches,
  memberMatchesQuery,
} from './fuzzySearch';
import type { MemberProfile } from 'types/member';

// A member who can't be found is indistinguishable from a member who doesn't
// exist — the failure is silent, which is why the thresholds below are pinned.

const member = (
  id: number,
  first: string,
  last: string,
  extra: Record<string, unknown> = {}
): MemberProfile =>
  ({
    id,
    email: `${first}.${last}@example.org`.toLowerCase(),
    screenName: `${first}${last[0]}`.toLowerCase(),
    name: { first, last, full: `${first} ${last}` },
    phone: '',
    rfid: '',
    vehicleRegistrationPlate: '',
    state: 'active',
    subscriptionStatus: 'active',
    ...extra,
  } as unknown as MemberProfile);

const MEMBERS = [
  member(42, 'José', "O'Brien", { phone: '+61400123456', rfid: '0004291' }),
  member(7, 'John', 'Smith'),
  member(8, 'Jürgen', 'Müller'),
  member(9, 'Catherine', 'Zhang', { vehicleRegistrationPlate: 'ABC123' }),
  member(10, 'Zoe', 'Ng'),
  member(11, '李', '明', { screenName: 'liming', email: 'li@example.org' }),
];

const search = (query: string) =>
  MEMBERS.filter((m) => memberMatchesQuery(m, query)).map((m) => m.id);

describe('normalizeSearchText', () => {
  it('strips Latin diacritics', () => {
    expect(normalizeSearchText('José')).toBe('jose');
    expect(normalizeSearchText('Müller')).toBe('muller');
  });

  it('flattens punctuation to spaces', () => {
    expect(normalizeSearchText("O'Brien")).toBe('o brien');
    expect(normalizeSearchText('de-la-Cruz')).toBe('de la cruz');
  });

  it('collapses whitespace', () => {
    expect(normalizeSearchText('  a   b  ')).toBe('a b');
  });

  // The API can return null for screenName/rfid/vehicleRegistrationPlate even
  // though the zod schema types them as strings.
  it('survives null, undefined and numbers', () => {
    expect(normalizeSearchText(null)).toBe('');
    expect(normalizeSearchText(undefined)).toBe('');
    expect(normalizeSearchText(42)).toBe('42');
  });

  // [a-z] here would erase non-Latin names entirely, recreating the very bug
  // this module exists to fix.
  it('keeps non-Latin scripts', () => {
    expect(normalizeSearchText('李明')).toBe('李明');
  });
});

describe('fuzzyTokenMatches', () => {
  it('matches an exact substring', () => {
    expect(fuzzyTokenMatches('smith', 'john smith')).toBe(true);
  });

  // Damerau, not plain Levenshtein: a transposition must cost 1, not 2.
  it('allows one edit on a five-character token', () => {
    expect(fuzzyTokenMatches('smiht', 'john smith')).toBe(true);
  });

  it('rejects two edits on a five-character token', () => {
    expect(fuzzyTokenMatches('smxht', 'john smith')).toBe(false);
  });

  // At three characters almost every name is one edit from every other.
  it('gives short tokens no typo budget', () => {
    expect(fuzzyTokenMatches('zoe', 'joe bloggs')).toBe(false);
  });

  it('matches the start of a longer word', () => {
    expect(fuzzyTokenMatches('catherne', 'catherine zhang')).toBe(true);
  });
});

describe('memberMatchesQuery', () => {
  it('finds an accented name from an unaccented query', () => {
    expect(search('jose')).toEqual([42]);
    expect(search('josé')).toEqual([42]);
    expect(search('JOSE')).toEqual([42]);
    expect(search('muller')).toEqual([8]);
  });

  it('ignores punctuation in either direction', () => {
    expect(search('obrien')).toEqual([42]);
    expect(search("o'brien")).toEqual([42]);
  });

  it('matches tokens in any order across fields', () => {
    expect(search('smith john')).toEqual([7]);
  });

  it('tolerates a transposition and an accent together', () => {
    expect(search('jhon')).toEqual([7]);
    expect(search('muler')).toEqual([8]);
  });

  it('searches phone, id, rfid, plate and screen name', () => {
    expect(search('+61400')).toEqual([42]);
    expect(search('42')).toEqual([42]);
    expect(search('0004291')).toEqual([42]);
    expect(search('ABC123')).toEqual([9]);
    expect(search('liming')).toEqual([11]);
  });

  // These have their own dropdown filter; matching them here would make
  // "active" return most of the table.
  it('does not search state or subscriptionStatus', () => {
    expect(search('active')).toEqual([]);
    expect(search('activ')).toEqual([]);
  });

  it('requires every token to match', () => {
    expect(search('john muller')).toEqual([]);
  });

  it('matches everything on an empty or blank query', () => {
    expect(search('')).toHaveLength(MEMBERS.length);
    expect(search('   ')).toHaveLength(MEMBERS.length);
  });

  it('caches per row object without leaking between members', () => {
    const [jose, john] = MEMBERS;
    expect(memberMatchesQuery(jose, 'jose')).toBe(true);
    expect(memberMatchesQuery(john, 'jose')).toBe(false);
    expect(memberMatchesQuery(jose, 'jose')).toBe(true);
  });
});
