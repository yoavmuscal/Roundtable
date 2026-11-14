import type { ReactNode } from 'react';
import type { Person } from '../contract';

const escapeRegExp = (value: string): string => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

export function CaptionText({ text, people }: { text: string; people: Person[] }) {
  const names = Array.from(
    new Set(people.flatMap((person) => [person.name, ...person.aliases]).map((name) => name.trim()).filter(Boolean)),
  ).sort((a, b) => b.length - a.length);
  if (!names.length) return <>{text}</>;
  const pattern = new RegExp(`(?<![\\p{L}\\p{N}_])(${names.map(escapeRegExp).join('|')})(?![\\p{L}\\p{N}_])`, 'giu');
  const parts: ReactNode[] = [];
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) parts.push(text.slice(cursor, index));
    parts.push(<strong key={`${match[0]}-${index}`}>{match[0]}</strong>);
    cursor = index + match[0].length;
  }
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <>{parts}</>;
}
