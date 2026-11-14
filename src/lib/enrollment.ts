/** The sentence inside the enrollment prompt's quotes, e.g. “Roundtable keeps this conversation private.” */
export function promptSentence(prompt: string): string {
  const quoted = prompt.match(/[“"]([^”"]+)[”"]/);
  return (quoted ? quoted[1] : prompt).trim();
}

function words(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/round\s+table/g, 'roundtable')
    .replace(/[^a-z0-9\s']/g, ' ')
    .split(/\s+/)
    .filter(Boolean);
}

/**
 * Did Argmax hear the enrollment sentence? Whisper may write "Round table keeps his
 * conversation private", so count how many of the sentence's words appear.
 */
export function sentenceHeard(prompt: string, heard: string | undefined, threshold = 0.6): boolean {
  if (!heard) return false;
  const target = words(promptSentence(prompt));
  if (!target.length) return false;
  const got = new Set(words(heard));
  const found = target.filter((word) => got.has(word)).length;
  return found / target.length >= threshold;
}
