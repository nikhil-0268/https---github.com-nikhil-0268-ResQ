# Voice input and dark glass update

The existing page grids, navigation, report section order and acoustic WAV recorder are preserved. The report input now contains a prominent microphone and live transcript; typing is a secondary edit mode. Acoustic Detection opens on its existing Record audio tab.

## Voice reporting

- Tap the microphone to request browser speech recognition. Nothing records on page load.
- Choose English or Nepali before starting. Actual language support depends on the browser speech service.
- Interim recognition results update the transcript in place. Browser speech-end finalizes the text; Stop does the same. Reports are never submitted automatically.
- A new dictation appends to existing text. Revised interim results replace earlier interim text instead of duplicating it.
- Permission denial, network errors, unsupported browsers and no-speech outcomes show a message and expose the typing fallback without erasing the report.
- Voice recognition may require an online browser service. Typed reports retain the existing offline queue.
- The recording and WAV encoding in `Signals.jsx` have not been rewritten. Speech-to-text is a separate report-input feature because the previous Citizen Reporting form had no dictation implementation.

## Files

- `src/VoiceReportInput.jsx`: mic, listening state, transcript, language and typing fallback.
- `src/speech.js`: recognition lifecycle and transcript assembly.
- `src/glass.css`: common frosted surfaces, dark background, contrast and reduced-motion styling.
- `tests/speech.test.js`: nine lifecycle checks using a fake recognition provider. These tests do not claim real microphone or speech-service accuracy.

## Checks

From this frontend directory:

```sh
npm test
npm run build
npm run preview -- --port 4173
```

The FastAPI backend should run separately on port 8000, as before. Open http://127.0.0.1:4173/report and refresh an already open tab after rebuilding.

Verified: production build, nine dictation lifecycle tests, browser typing/edit toggle, dashboard and drawer appearance, and a 390px mobile viewport with no horizontal overflow. A physical microphone and live browser speech service were not exercised during automated validation.
