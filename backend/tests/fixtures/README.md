`argmax-stream-sample.txt` reproduces the exact block format printed by
`whisperkit-cli transcribe --stream --word-timestamps` (Argmax CLI 1.1.1, the binary is `argmax-cli`)
on the demo M2 Mac: blocks separated by `---`, each with `Confirmed segment:`, `Unconfirmed segment:`
and `Current text:` lines carrying Whisper control tokens. The words are neutral test text rather
than the room audio that was captured.
