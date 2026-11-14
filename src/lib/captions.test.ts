import { describe, expect, it } from 'vitest';
import { currentSentence } from './captions';

describe('currentSentence', () => {
  it('keeps only the sentence being spoken', () => {
    expect(currentSentence('Okay. Let us map the demo. Should we start')).toBe('Should we start');
  });

  it('shows a finished sentence until the next one begins', () => {
    expect(currentSentence('Is this working?')).toBe('Is this working?');
    expect(currentSentence('Is this working? Yes')).toBe('Yes');
  });

  it('leaves text without punctuation alone', () => {
    expect(currentSentence('  hello   there ')).toBe('hello there');
  });

  it('keeps a short finished affirmation attached to the sentence before it', () => {
    expect(currentSentence('I mean almost perfect. Yeah.')).toBe('I mean almost perfect. Yeah.');
    expect(currentSentence('The actual subtitling is much better. Yes.')).toBe('The actual subtitling is much better. Yes.');
  });
});
