import type { Person } from '../contract';

const escapeRegExp = (value: string): string => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

export function containsName(text: string, nameOrAlias: string): boolean {
  const needle = nameOrAlias.trim();
  if (!needle) return false;
  const pattern = new RegExp(`(?<![\\p{L}\\p{N}_])${escapeRegExp(needle)}(?![\\p{L}\\p{N}_])`, 'iu');
  return pattern.test(text);
}

export function matchingPeople(text: string, people: Person[]): Person[] {
  return people.filter((person) =>
    [person.name, ...person.aliases].some((alias) => containsName(text, alias)),
  );
}

export function hasNameAlert(text: string, people: Person[]): boolean {
  return matchingPeople(text, people).length > 0;
}
