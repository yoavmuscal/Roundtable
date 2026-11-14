import { describe, expect, it } from 'vitest';
import { promptSentence, promptSentences, sentenceHeard, sentencesHeard } from './enrollment';

const prompt = 'Yoav, please say: “Roundtable keeps this conversation private.”';
const both = 'Cello, please read both sentences: “Roundtable keeps this conversation private.” “Everyone at the table should be easy to follow.”';

describe('enrollment sentence check', () => {
  it('extracts the quoted sentence', () => {
    expect(promptSentence(prompt)).toBe('Roundtable keeps this conversation private.');
  });

  it('accepts how Whisper actually wrote it on the demo Mac', () => {
    expect(sentenceHeard(prompt, 'Round table keeps his conversation private.')).toBe(true);
  });

  it('rejects unrelated speech and silence', () => {
    expect(sentenceHeard(prompt, 'Is this working?')).toBe(false);
    expect(sentenceHeard(prompt, undefined)).toBe(false);
  });

  it('checks both enrollment sentences independently', () => {
    expect(promptSentences(both)).toHaveLength(2);
    expect(sentencesHeard(both, 'Round table keeps this conversation private.')).toEqual([true, false]);
    expect(sentenceHeard(both, 'Roundtable keeps this conversation private. Everyone at the table should be easy to follow.')).toBe(true);
  });
});
