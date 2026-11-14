/** Quoted sentences in the enrollment prompt (one or two). */
export function promptSentences(prompt: string): string[] {
  const quoted = [...prompt.matchAll(/[“"]([^”"]+)[”"]/g)].map((match) => match[1].trim()).filter(Boolean);
  return quoted.length ? quoted : [prompt.trim()].filter(Boolean);
}

/** The first quoted sentence. Kept for callers that expect a single line. */
export function promptSentence(prompt: string): string {
  return promptSentences(prompt)[0] ?? '';
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
function coverage(sentence: string, heard: string): number {
  const target = words(sentence);
  if (!target.length) return 0;
  const got = new Set(words(heard));
  return target.filter((word) => got.has(word)).length / target.length;
}

/** Which prompt sentences Argmax has heard (word overlap, so "Round table" still counts). */
export function sentencesHeard(prompt: string, heard: string | undefined, threshold = 0.6): boolean[] {
  const sentences = promptSentences(prompt);
  if (!heard) return sentences.map(() => false);
  return sentences.map((sentence) => coverage(sentence, heard) >= threshold);
}

export function sentenceHeard(prompt: string, heard: string | undefined, threshold = 0.6): boolean {
  const flags = sentencesHeard(prompt, heard, threshold);
  return flags.length > 0 && flags.every(Boolean);
}
