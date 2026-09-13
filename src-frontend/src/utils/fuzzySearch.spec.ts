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
  member(9, 'Catherine', 'Zhang', {
    vehicleRegistrationPlate: 'ABC123',
    subscriptionStatus: 'cancelling',
  }),
  member(10, 'Zoe', 'Ng', {
    state: 'accountonly',
    subscriptionStatus: 'pending',
  }),
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

  // Harakat and niqqud are stored but almost never typed, so they have to fold
  // away exactly like a Latin accent does.
  it('folds away marks in other scripts', () => {
    expect(normalizeSearchText('عَرَبِيّ')).toBe('عربي');
    expect(normalizeSearchText('עִבְרִית')).toBe('עברית');
    expect(normalizeSearchText('Ångström')).toBe('angstrom');
  });

  // Letting the separator pass eat the marks instead would shred one name into
  // single-letter fragments, hiding the member as thoroughly as the accent bug.
  it('leaves a mark-heavy name as a single token', () => {
    expect(normalizeSearchText('عَرَبِيّ').split(' ')).toHaveLength(1);
    expect(normalizeSearchText('हिन्दी').split(' ')).toHaveLength(1);
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

  // Run-together screen names and email local parts are one long word, so a
  // typo'd query has to match a prefix of it and not just the whole thing.
  it('tolerates a typo against a prefix of a much longer word', () => {
    expect(fuzzyTokenMatches('smiht', 'smithsonian')).toBe(true);
    expect(fuzzyTokenMatches('obrein', 'obrienmurphy')).toBe(true);
    expect(fuzzyTokenMatches('jhonsmith', 'johnsmithson')).toBe(true);
  });

  // The prefix window must not become a licence to match anything that merely
  // starts with the same letters.
  it('still rejects a prefix that is over budget', () => {
    expect(fuzzyTokenMatches('cathrne', 'catherinezhang')).toBe(false);
    expect(fuzzyTokenMatches('smxht', 'smithsonian')).toBe(false);
  });
});

describe('memberMatchesQuery', () => {
  // The bug this module exists to fix, in the script where it bites hardest.
  it('finds a mark-bearing name from a bare query', () => {
    const arabic = member(12, 'عَرَبِيّ', 'الرَشِيد');
    expect(memberMatchesQuery(arabic, 'عربي')).toBe(true);
    expect(memberMatchesQuery(arabic, 'الرشيد')).toBe(true);
  });

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

  // `state` has its own dropdown; matching it here would make "active" return
  // most of the table.
  it('does not search state', () => {
    expect(search('accountonly')).toEqual([]);
    expect(search('noob')).toEqual([]);
  });

  // `subscriptionStatus` has no dropdown, so search is the only way to reach it.
  it('searches subscriptionStatus', () => {
    expect(search('cancelling')).toEqual([9]);
    expect(search('pending')).toEqual([10]);
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
