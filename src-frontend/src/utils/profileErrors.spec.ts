import { describe, it, expect } from 'vitest';
import { errorKeys } from './profileErrors';

describe('errorKeys', () => {
  it('reads the message of a conflict', () => {
    expect(
      errorKeys({
        status: 409,
        data: { message: 'error.accountAlreadyExists' },
      })
    ).toEqual(['error.accountAlreadyExists']);
  });

  it('lists every field error, once each', () => {
    expect(
      errorKeys({
        status: 400,
        data: {
          firstName: ['error.fieldRequired'],
          lastName: ['error.fieldRequired'],
          phone: ['validation.invalidPhone'],
        },
      })
    ).toEqual(['error.fieldRequired', 'validation.invalidPhone']);
  });

  it('gives nothing for other failures', () => {
    expect(errorKeys({ status: 500, data: { message: 'x' } })).toEqual([]);
    expect(errorKeys({ status: 400, data: 'Bad Request' })).toEqual([]);
    expect(errorKeys(undefined)).toEqual([]);
  });
});
