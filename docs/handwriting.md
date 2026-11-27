# My handwriting

Upload photos of your notebook pages, tell the app what each line says, and it can write text in your own hand as an SVG for the plotter.

Everything is offline except the optional OCR step. Samples live in `data/handwriting/` (gitignored).

## Tomorrow

1. Start the app: `python app.py` (or `python app.py --lan` to reach it from your phone on the same Wi-Fi; the console prints the LAN URL).
2. Open `http://127.0.0.1:8775/handwriting.html`.
3. **Upload pages.** Pick one or more photos (JPEG or PNG). Use even light and get the whole page in frame. Each photo appears in the Samples list.
4. **Type the transcriptions.** Open a sample. The photo shows yellow boxes (guessed letters), blue boxes (matched letters) and green boxes (letters you set by hand). For each text line, type what it says and press Save. Letters are matched to the boxes left to right.
5. **Fix mistakes.** Click a box on the photo and type its letter. An empty answer clears it.
6. **Write text.** Type text in section 3, set the letter height in mm (the height of a typical letter, about 8 for a notebook), and press Render. The SVG is saved to `data/handwriting/last_render.svg`.
7. **Plot it.** Convert the file with the existing tool, using the full path:
   `python tools/lily_run.py "C:\Users\caleb_u04yywz\VS Code Stuff\davinchi\data\handwriting\last_render.svg"`
   This only writes jog commands. Nothing runs on the machine until you run it yourself.

The more lines you label, the more varied the result. Each letter is drawn from a random sample of yours. Letters you have not labeled fall back to the built-in single-stroke font (uppercase, digits and punctuation only).

## Reading messy writing (optional)

Section 2 has a "Try to read the page" button. It needs one of:

- **Tesseract:** `pip install pytesseract`, plus the tesseract program installed and on PATH.
- **Claude:** `pip install anthropic`, and set `ANTHROPIC_API_KEY` in your environment before starting the app. The request is sent to the API and billed. The key is never stored in the repo.

With neither set, the button shows "No OCR backend configured".

## Limits

- **Photos:** JPEG, PNG or WebP only. Export HEIC photos as JPEG first.
- **Ruled lines:** long straight lines are removed heuristically. Very faint or angled rules may still leak through.
- **Letter matching:** when the number of letters and boxes differs, matching is a position guess and the boxes show as yellow. Check them. Retyping a line's transcription resets that line's labels, so re-do manual fixes after changing the text.
- **Letter height:** `size_mm` is the height of a typical letter. Capitals and descenders are scaled with it.

## Data and tests

- Originals: `data/handwriting/samples/<id>.<ext>`. Deskewed pages: `<id>_page.png` beside them.
- Index: `data/handwriting/index.json`. Glyph candidates and labels: `data/handwriting/glyphs.json`.
- Back up `data/handwriting/` if the labels matter to you. There is no delete button yet; remove a sample by deleting its files and its entries in the two JSON files.
- Tests (synthetic images, no camera or API calls): `python -m pytest tests/test_handwriting.py -q`

## API

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/handwriting/upload` | `{"filename": "p.jpg", "data": "<base64>"}` (up to 25 MB) | `{id, lines, glyphs}` |
| GET | `/api/handwriting/samples` | | `{samples: [...]}` |
| GET | `/api/handwriting/sample/<id>` | | lines and glyph boxes |
| GET | `/api/handwriting/sample/<id>/page.png` | | deskewed page |
| POST | `/api/handwriting/transcribe` | `{"line": "<line id>", "text": "..."}` | `{line, labeled}` |
| POST | `/api/handwriting/label` | `{"glyph": "<glyph id>", "char": "a"}` (`""` clears) | `{glyph}` |
| POST | `/api/handwriting/read` | `{"id": <sample id>}` | `{backend, text}` or 503 |
| POST | `/api/handwriting/render` | `{"text": "...", "size_mm": 8, "seed": 1}` | `{svg, file}` |
