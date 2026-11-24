# Cleanly Censorship

**Find listed words in text, audio and video, and cover them with music, a beep or replacement text. Runs locally on your computer.**

Cleanly was started to make content safer to consume: for parents, teachers, companies and creators who want a clean version of a video, recording or document without sending it anywhere.

> 🚧 **Status: early development (v1 in progress).** Text, JSON and subtitle (.srt) censoring works now. Audio and video are next. The features below describe what v1 is being built to do.

---

## Example

```
Original:  "What the [bad word] was that?"
Cleaned:   "What the ♪ ♪ ♪ was that?"
```

---

## Features (v1 goals)

- **Three input types:** text (`.txt`, `.json`, `.srt`), audio and video
- **Several ways to cover a word:** music clip, beep, mute, lowered volume (duck), reversed audio, or `***` / replacement text
- **Built-in Standard word list** for English, with a severity tag on every word
- **Your own list:** edit the Standard list, or use only your own words
- **Review before export:** see every word that was found, with a 2-second preview, and uncover any false matches
- **Private by design:** no sign-up, no upload; everything runs on your computer

---

## How it works

```
Input ─┬─ Text / JSON / SRT ───────────────────────────► find words ─► censor text ─► output
       │
       └─ Audio / Video ─► extract audio ─► separate voice | background (optional)
                                              │
                         clean voice ─► transcribe + word timestamps ─► find words
                                                                          │
                      censor windows (music / beep / mute / duck / reverse)
                                                                          │
                rebuild only those windows ─► stitch into original ─► remux ─► output
```

1. **Get the words.** Text is read directly. For audio and video, speech is transcribed with word-level timestamps.
2. **Separate (optional).** If there's background music, the voice is separated from it first, which makes transcription more accurate.
3. **Match.** Words are compared against your chosen word list.
4. **Censor.** Each matched word's time window is covered by the chosen effect.
5. **Reassemble.** Only the censored windows are rebuilt. The rest of the file stays as original quality, joined with short crossfades.
6. **Output.** You get the cleaned file plus a report of what was covered.

---

## Word lists

| Mode | What it does |
|---|---|
| **Standard** | The built-in list, no changes |
| **Customized** | Start from Standard: remove words you don't want censored, add your own |
| **My List** | Only your own words |

```
final list = (Standard − words removed) + words added
```

### Strictness

Every word in the Standard list has a severity tag:

| Level | What gets censored |
|---|---|
| **Light** | Slurs only |
| **Moderate** | Strong words + slurs |
| **Strict** | Everything, including mild words |

Lists are plain JSON files, so they can be exported and shared, for example between teachers.

---

## Privacy

- **No sign-up, no account**
- **No upload:** works offline after the first setup (the speech models are downloaded once)
- **No history:** temporary files, separated audio and transcripts are deleted after export

## Limitations

Speech recognition is not perfect. Accents, fast speech and loud background music can cause missed or wrong matches. Cleanly **reduces** bad language; it does not guarantee its removal. **Always review the result before sharing it**, especially for children's content.

---

## Tech stack

| Part | Tool |
|---|---|
| Language | Python 3.11 / 3.12 |
| Speech-to-text | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (English models) |
| Voice separation | [Demucs](https://github.com/facebookresearch/demucs) |
| Audio processing | numpy, soundfile |
| Video | [FFmpeg](https://ffmpeg.org/) |
| CLI | argparse (standard library) |
| Local web UI | Gradio / FastAPI |

---

## Roadmap

### v1: English
- [x] Text censoring with the Standard list (JSON, severity tags): `.txt`, `.json`, `.srt`
- [ ] Basic audio beep from a command line tool
- [ ] Word timestamps, music clips, stitching with crossfades
- [ ] Video support and voice separation
- [ ] Local web UI: word-list editor and review screen
- [ ] Desktop package (if people find it useful)

### v2: ideas
- [ ] More languages (Hindi / Hinglish, Gujarati and others)
- [ ] Optional AI check for context, with your own API key (opt-in; sends transcript text only, never the video) or a local model
- [ ] Censor subtitles and on-screen text
- [ ] Real-time mode

---

## Try it now (v0.1: text, JSON and subtitle files)

```bash
git clone https://github.com/damasiyachiranj/cleanly-censorship.git
cd cleanly-censorship
pip install -e .

cleanly examples/sample.txt
cleanly examples/sample.srt --mode customized --list examples/my_list.json --effect symbol
cleanly notes.json --strictness moderate --effect replace --replacement "beep" --report report.json
```

| Option | Values |
|---|---|
| `--mode` | `standard` (default), `customized`, `mylist` |
| `--strictness` | `light`, `moderate`, `strict` (default) |
| `--list` | your list file: `{"remove": [...], "add": [...]}` (see `examples/my_list.json`) |
| `--effect` | `stars` → `d***` (default), `full` → `****`, `symbol` → `♪`, `replace` → your word |
| `--report` | save a JSON report of what was covered (words shown masked) |

Run the tests with `pip install -e ".[dev]"` and `pytest`.

### Planned (audio and video)

```bash
cleanly video.mp4 --mode standard --strictness strict --effect music
```

The step-by-step algorithms are in [docs/ALGORITHM.md](docs/ALGORITHM.md).

---

## Contributing

Contributions are welcome, especially to the word lists. Open an issue or a pull request to suggest words, variants or severity changes.

## License

[MIT](LICENSE). Third-party word lists or models included in this project keep their own licenses and are credited here.

## Author

Built by [@damasiyachiranj](https://github.com/damasiyachiranj).
