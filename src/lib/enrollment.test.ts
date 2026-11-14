import { describe, expect, it } from 'vitest';
import { promptSentence, sentenceHeard } from './enrollment';

const prompt = 'Yoav, please say: “Roundtable keeps this conversation private.”';

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
});
