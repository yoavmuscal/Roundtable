/**
 * The sentence a bubble should show: the active sentence being spoken, while
 * keeping short finished affirmations ("Yeah.", "Yes.") attached to the
 * sentence right before them so the main thought never disappears.
 */
export function currentSentence(text: string): string {
  const clean = text.replace(/\s+/g, ' ').trim();
  if (!clean) return '';
  const sentences = clean.split(/(?<=[.?!…])\s+/).filter(Boolean);
  if (sentences.length <= 1) return clean;
  const last = sentences[sentences.length - 1]!;
  const lastWords = last.split(/\s+/).length;
  // If the trailing fragment already has ending punctuation and is just 1-2 words
  // (e.g. "I mean almost perfect. Yeah."), keep the preceding sentence with it.
  if (/[.?!…]$/.test(last) && lastWords <= 2) {
    return `${sentences[sentences.length - 2]} ${last}`;
  }
  return last;
}
