import { describe, expect, it } from 'vitest';
import { buildCsvRows, memberEmailList, toCsv } from './memberExport';

const rows = [
  { name: 'Ada', email: 'ada@example.com', excludeFromEmailExport: false },
  { name: 'Bob', email: 'bob@example.com', excludeFromEmailExport: true },
  { name: 'Cy', email: 'cy@example.com', excludeFromEmailExport: false },
];

describe('buildCsvRows', () => {
  it('starts with a header row and maps each value', () => {
    expect(
      buildCsvRows(rows.slice(0, 1), [
        { header: 'Name', value: (row) => row.name },
        { header: 'Shout', value: (row) => row.name.toUpperCase() },
      ])
    ).toEqual([
      ['Name', 'Shout'],
      ['Ada', 'ADA'],
    ]);
  });

  it('writes missing values as empty cells', () => {
    expect(
      buildCsvRows(rows.slice(0, 1), [
        { header: 'Null', value: () => null },
        { header: 'Undefined', value: () => undefined },
        { header: 'Zero', value: () => 0 },
      ])[1]
    ).toEqual(['', '', '0']);
  });
});

describe('memberEmailList', () => {
  it('leaves out members excluded from email exports', () => {
    expect(memberEmailList(rows)).toBe('ada@example.com,cy@example.com');
  });

  it('is empty for no rows', () => {
    expect(memberEmailList([])).toBe('');
  });
});

describe('toCsv', () => {
  it('quotes values that need it', () => {
    expect(
      toCsv(
        [{ name: 'Smith, "Jo"' }],
        [{ header: 'Name', value: (row) => row.name }]
      )
    ).toBe('Name\n"Smith, ""Jo"""\n');
  });
});
