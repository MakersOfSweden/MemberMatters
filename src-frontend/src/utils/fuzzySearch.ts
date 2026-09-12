// Fuzzy matching for the admin members list. Quasar's default table filter is a
// raw substring match, so a single stored accent ("José" vs a search for "jose")
// hides a member from an admin entirely. This normalises accents, case and
// punctuation away and tolerates a small number of typos on top.

import type { MemberProfile } from 'types/member';

// Every mark, not just the U+0300-U+036F block NFD splits Latin accents into:
// Arabic harakat and Hebrew niqqud are stored but almost never typed, so "عربي"
// has to find "عَرَبِيّ" for the same reason "jose" has to find "José". Stripping
// them here and not leaving them to the separator pass below matters — marks
// aren't \p{L}, so that pass would shred one name into single-letter fragments.
const COMBINING_MARKS = /\p{M}/gu;

// Lowercases, drops the marks, then flattens anything that isn't a letter or
// digit to a space so "O'Brien" and "de-la-cruz" tokenise the way an admin would
// type them. \p{L} rather than [a-z] so non-Latin names survive instead of
// normalising to empty.
export function normalizeSearchText(value: unknown): string {
  if (value === null || value === undefined) return '';
  return String(value)
    .normalize('NFD')
    .replace(COMBINING_MARKS, '')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim();
}

// Damerau-Levenshtein (optimal string alignment) from `a` to the closest prefix
// of `b`, abandoned as soon as an entire row exceeds `budget`. Transpositions
// cost 1 rather than 2, because "jhon" for "john" is the single most common way
// a name gets mistyped. Three rolling rows rather than a full matrix — this runs
// over every word of every member on each keystroke.
//
// Closest prefix, not whole string: the final row holds the distance to every
// prefix of `b`, so taking its minimum is what lets a typo'd query match the
// start of a longer name. Reading only the last cell would miss those.
function boundedPrefixDistance(a: string, b: string, budget: number): number {
  if (a.length - b.length > budget) return budget + 1;

  let beforePrevious: number[] = [];
  let previous = Array.from({ length: b.length + 1 }, (_, i) => i);

  for (let i = 1; i <= a.length; i++) {
    const current = [i];
    let rowMin = i;

    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      let distance = Math.min(
        previous[j] + 1,
        current[j - 1] + 1,
        previous[j - 1] + cost
      );
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        distance = Math.min(distance, beforePrevious[j - 2] + 1);
      }
      current.push(distance);
      if (distance < rowMin) rowMin = distance;
    }

    if (rowMin > budget) return budget + 1;
    beforePrevious = previous;
    previous = current;
  }

  return Math.min(...previous.slice(Math.max(0, a.length - budget)));
}

// Short tokens get no typo budget at all: at two or three characters almost
// every name is within one edit of every other, which would defeat the search.
function editBudget(token: string): number {
  if (token.length <= 3) return 0;
  if (token.length <= 7) return 1;
  return 2;
}

// `haystack` must already be normalised.
export function fuzzyTokenMatches(token: string, haystack: string): boolean {
  if (!token) return true;
  if (haystack.includes(token)) return true;

  const budget = editBudget(token);
  if (budget === 0) return false;

  // Per word, against a leading window long enough to hold any prefix that could
  // still be within budget, so "catherne" finds "catherine" and "obrein" finds
  // the "obrien" buried in a run-together screen name.
  return haystack
    .split(' ')
    .some(
      (word) =>
        boundedPrefixDistance(
          token,
          word.slice(0, token.length + budget),
          budget
        ) <= budget
    );
}

// The member list is fetched once and re-filtered on every keystroke, so
// normalising each row's fields every time is pure waste. A refetch replaces the
// rows wholesale, so keying on the row object is what keeps this correct; the
// WeakMap is what stops it pinning the replaced rows in memory.
const haystackCache = new WeakMap<MemberProfile, string>();

// `state` is absent because it has its own dropdown, and fuzzy-matching it would
// make "active" sweep in most of the table. `subscriptionStatus` is present
// because it has no dropdown — without it "cancelling" and "pending" would be
// unreachable by any means, though the column is right there on screen.
function memberHaystack(member: MemberProfile): string {
  const cached = haystackCache.get(member);
  if (cached !== undefined) return cached;

  const haystack = [
    member.name?.full,
    member.screenName,
    member.email,
    member.rfid,
    member.vehicleRegistrationPlate,
    member.phone,
    member.subscriptionStatus,
    member.id,
  ]
    .map(normalizeSearchText)
    .filter(Boolean)
    .join(' ');

  haystackCache.set(member, haystack);
  return haystack;
}

// Every token must match somewhere, but each can match a different field — that
// is what lets "smith john" find "John Smith".
export function memberMatchesQuery(
  member: MemberProfile,
  query: string
): boolean {
  const tokens = normalizeSearchText(query).split(' ').filter(Boolean);
  if (!tokens.length) return true;

  const haystack = memberHaystack(member);
  return tokens.every((token) => fuzzyTokenMatches(token, haystack));
}
