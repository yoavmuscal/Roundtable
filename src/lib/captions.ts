/**
 * The sentence a bubble should show: only the one currently being spoken.
 * A finished sentence disappears as soon as the speaker starts the next one.
 */
export function currentSentence(text: string): string {
  const clean = text.replace(/\s+/g, ' ').trim();
  if (!clean) return '';
  // Split after . ? ! (keeping the mark) when followed by a space.
  const sentences = clean.split(/(?<=[.?!…])\s+/).filter(Boolean);
  return sentences[sentences.length - 1] ?? clean;
}
