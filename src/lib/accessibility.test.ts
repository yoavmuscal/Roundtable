import { describe, expect, it } from 'vitest';
import { containsName, matchingPeople } from './accessibility';
import { DEFAULT_PEOPLE } from '../contract';

describe('name alerts', () => {
  it('matches an enrolled name case-insensitively at a word boundary', () => {
    expect(containsName('Yoav, what do you think?', 'yoav')).toBe(true);
  });

  it('does not match inside another word', () => {
    expect(containsName('The yoavian example is unrelated', 'yoav')).toBe(false);
  });

  it('matches aliases as well as display names', () => {
    const people = [{ ...DEFAULT_PEOPLE[0], aliases: ['Yoyo'] }];
    expect(matchingPeople('Yoyo, can you check this?', people)).toHaveLength(1);
  });
});
