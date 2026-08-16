// Fuzzy matching for the admin members list. Quasar's default table filter is a
// raw substring match, so a single stored accent ("José" vs a search for "jose")
// hides a member from an admin entirely. This normalises accents, case and
// punctuation away and tolerates a small number of typos on top.

import type { MemberProfile } from 'types/member';

// Only the Latin/Greek/Cyrillic combining block, so scripts where marks carry
// meaning (Devanagari, Arabic, Hebrew) are left intact.
const COMBINING_MARKS = /[̀-ͯ]/g;

// Strips the combining marks left behind by NFD (é -> e + U+0301 -> e),
// lowercases, then flattens anything that isn't a letter or digit to a space so
// "O'Brien" and "de-la-cruz" tokenise the way an admin would type them. \p{L}
// rather than [a-z] so non-Latin names survive instead of normalising to empty.
export function normalizeSearchText(value: unknown): string {
  if (value === null || value === undefined) return '';
  return String(value)
    .normalize('NFD')
    .replace(COMBINING_MARKS, '')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim();
}

// Damerau-Levenshtein (optimal string alignment), abandoned as soon as an
// entire row exceeds `budget`. Transpositions cost 1 rather than 2, which
// matters because "jhon" for "john" is the single most common way a name gets
// mistyped. Three rolling rows rather than a full matrix — this runs over every
// word of every member on each keystroke.
function boundedEditDistance(a: string, b: string, budget: number): number {
  if (Math.abs(a.length - b.length) > budget) return budget + 1;

  let beforePrevious: number[] = [];
  let previous = Array.from({ length: b.length + 1 }, (_, i) => i);

  for (let i = 1; i <= a.length; i++) {
    const current = [i];
    let rowMin = i;

    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      let distance = Math.min(
        previous[j] + 1, // deletion
        current[j - 1] + 1, // insertion
        previous[j - 1] + cost // substitution
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

  return previous[b.length];
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

  // Compared per word, and against leading windows of longer words, so a
  // mistyped query still matches the start of a longer name ("catherne" ->
  // "catherine").
  return haystack.split(' ').some((word) => {
    if (!word) return false;
    if (word.length <= token.length + budget) {
      return boundedEditDistance(token, word, budget) <= budget;
    }
    return (
      boundedEditDistance(
        token,
        word.slice(0, token.length + budget),
        budget
      ) <= budget
    );
  });
}

// The member list is fetched once and then re-filtered on every keystroke, so
// normalising each row's fields every time is pure waste. Keyed on the row
// object, which only changes when the list is refetched — a WeakMap means that
// refetch invalidates the cache for free.
const haystackCache = new WeakMap<MemberProfile, string>();

// Deliberately excludes `state` and `subscriptionStatus`: low-cardinality enums
// with their own dropdown filter, and fuzzy-matching them makes a query like
// "active" sweep in most of the table.
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
