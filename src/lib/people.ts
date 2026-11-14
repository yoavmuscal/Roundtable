import type { Person, SpeakerShape } from '../contract';

/** Colorblind-safe identity palette for seats p1–p4 (build guide 6.9). */
export const SPEAKER_SLOTS: Array<{ id: string; color: string; shape: SpeakerShape }> = [
  { id: 'p1', color: '#8B7CF6', shape: 'circle' },
  { id: 'p2', color: '#2DD4A7', shape: 'square' },
  { id: 'p3', color: '#F5A524', shape: 'diamond' },
  { id: 'p4', color: '#F472B6', shape: 'triangle' },
];

export const MAX_PEOPLE = SPEAKER_SLOTS.length;
export const MIN_PEOPLE = 1;

/** Append the next free seat; returns the same list when all four seats are taken. */
export function addPerson(people: Person[]): Person[] {
  if (people.length >= MAX_PEOPLE) return people;
  const slot = SPEAKER_SLOTS.find((candidate) => !people.some((person) => person.id === candidate.id));
  if (!slot) return people;
  const next = { id: slot.id, name: `Speaker ${people.length + 1}`, aliases: [], color: slot.color, shape: slot.shape };
  return [...people, next].sort((a, b) => a.id.localeCompare(b.id));
}

/** Remove a person; never drops below one seat. */
export function removePerson(people: Person[], personId: string): Person[] {
  if (people.length <= MIN_PEOPLE) return people;
  return people.filter((person) => person.id !== personId);
}

/** Default seats along the far edge, evenly spread for however many people there are. */
export function defaultSeats(people: Person[], tableWidth = 1.8): Record<string, { x: number; y: number }> {
  const seats: Record<string, { x: number; y: number }> = {};
  people.forEach((person, index) => {
    seats[person.id] = { x: (tableWidth * (index + 1)) / (people.length + 1), y: -0.45 };
  });
  return seats;
}
