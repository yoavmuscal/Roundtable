import { describe, expect, it } from 'vitest';
import { DEFAULT_PEOPLE } from '../contract';
import { addPerson, defaultSeats, removePerson } from './people';

describe('people helpers', () => {
  it('adds up to four people with distinct colors and shapes', () => {
    const four = addPerson(DEFAULT_PEOPLE);
    expect(four).toHaveLength(4);
    expect(four[3]).toMatchObject({ id: 'p4', shape: 'triangle' });
    expect(addPerson(four)).toBe(four);
    expect(new Set(four.map((person) => person.color)).size).toBe(4);
  });

  it('reuses a freed seat id and never drops below one person', () => {
    const two = removePerson(DEFAULT_PEOPLE, 'p2');
    expect(two.map((person) => person.id)).toEqual(['p1', 'p3']);
    expect(addPerson(two).map((person) => person.id)).toEqual(['p1', 'p2', 'p3']);
    const one = removePerson(two, 'p3');
    expect(removePerson(one, 'p1')).toBe(one);
  });

  it('spreads default seats along the far edge', () => {
    const seats = defaultSeats(DEFAULT_PEOPLE.slice(0, 2));
    expect(seats.p1.x).toBeCloseTo(0.6);
    expect(seats.p2.x).toBeCloseTo(1.2);
    expect(seats.p1.y).toBe(-0.45);
  });
});
