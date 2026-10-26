// Shared by the admin member lists' "Export CSV" and "Copy Email List" so both
// tabs export exactly the rows on screen, in the same shape.

// The sync build: the default csv-stringify entry is a Node stream Transform,
// which crashes in the browser bundle ("Cannot read properties of undefined
// (reading 'call')"), so Export CSV never produced a file.
import { stringify } from 'csv-stringify/sync';

export interface CsvColumn<T> {
  header: string;
  value: (row: T) => string | number | null | undefined;
}

// A header row, then one row per member. Missing values become empty cells
// rather than the string "null".
export function buildCsvRows<T>(
  rows: T[],
  columns: CsvColumn<T>[]
): string[][] {
  return [
    columns.map((column) => column.header),
    ...rows.map((row) =>
      columns.map((column) => {
        const value = column.value(row);
        return value === null || value === undefined ? '' : String(value);
      })
    ),
  ];
}

export function toCsv<T>(rows: T[], columns: CsvColumn<T>[]): string {
  return stringify(buildCsvRows(rows, columns));
}

interface EmailExportable {
  email: string;
  excludeFromEmailExport: boolean;
}

// Members an admin has opted out of email exports are left off.
export function emailExportMembers<T extends EmailExportable>(rows: T[]): T[] {
  return rows.filter((row) => !row.excludeFromEmailExport);
}

export function memberEmailList(rows: EmailExportable[]): string {
  return emailExportMembers(rows)
    .map((row) => row.email)
    .join(',');
}
