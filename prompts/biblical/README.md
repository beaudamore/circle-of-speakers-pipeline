# Biblical Speaker Prompts

System prompts for biblical figures, used as Open WebUI model system prompts so the **Circle of Speakers** pipeline can route to them by tag.

## Layout

```text
biblical/
├── old-testament/          21 figures — Hebrew Bible
├── new-testament/
│   ├── james-the-brother-of-jesus.md   non-apostle NT figure
│   ├── jude-contender-for-the-faith.md non-apostle NT figure
│   └── apostles/           15 figures — the 12 + Paul + Barnabas + Matthias
└── README.md               (this file)
```

Each `.md` file is a self-contained system prompt that:

- Establishes the figure's first-person identity
- Anchors the voice in 3-5 KJV exemplars (or other primary text)
- Specifies banned-opener / register guidance
- Closes with `SPEAK ONLY AS X. First person. Never break character.`

This format aligns with the Open WebUI **Model** system-prompt slot. The Circle of Speakers pipeline filters which models participate via the `SPEAKER_TAGS` valve — for biblical-circle, that's `biblical`. Each model is also tagged with `old-testament`, `new-testament`, or `apostles` to enable narrower circles in future deployments.

## Roster — 38 figures

### Old Testament (21)

| File | Trained as LoRA voice? |
| --- | :---: |
| `amos-the-shepherd-of-tekoa.md` | ✅ |
| `daniel-the-exile-in-babylon.md` | ✅ |
| `david-the-sweet-psalmist.md` | ✅ |
| `ezekiel-the-priest-among-exiles.md` | ✅ |
| `habakkuk-the-wrestler-with-god.md` | ✅ |
| `haggai-the-rebuilder.md` | ✅ |
| `hosea-the-prophet-of-wounded-love.md` | ✅ |
| `isaiah-the-court-prophet.md` | ✅ |
| `jeremiah-the-weeping-prophet.md` | ✅ |
| `job-the-righteous-sufferer.md` | ✅ |
| `joel-the-prophet-of-the-day.md` | ✅ |
| `jonah-the-reluctant-prophet.md` | ✅ |
| `joshua-the-commander.md` | ✅ |
| `malachi-the-final-prophet.md` | ✅ |
| `micah-the-countryside-prophet.md` | ✅ |
| `moses-the-liberator-and-lawgiver.md` | ✅ |
| `nahum-the-prophet-against-nineveh.md` | ✅ |
| `obadiah-the-prophet-against-edom.md` | ✅ |
| `solomon-the-wise-and-foolish.md` | ✅ |
| `zechariah-the-prophet-of-visions.md` | ✅ |
| `zephaniah-the-day-and-the-song.md` | ✅ |

### New Testament — non-apostles (2)

| File | Trained as LoRA voice? |
| --- | :---: |
| `james-the-brother-of-jesus.md` | ✅ |
| `jude-contender-for-the-faith.md` | ✅ |

### New Testament — apostles (15)

| File | Trained as LoRA voice? |
| --- | :---: |
| `andrew-the-first-called.md` | prompt-only |
| `barnabas-the-son-of-encouragement.md` | prompt-only |
| `bartholomew-also-called-nathanael.md` | prompt-only |
| `james-son-of-alphaeus.md` | prompt-only |
| `james-son-of-zebedee.md` | prompt-only |
| `john-apostle-the-beloved-disciple.md` | ✅ |
| `judas-iscariot-the-betrayer.md` | prompt-only |
| `matthew-levi-the-tax-collector.md` | prompt-only |
| `matthias-the-chosen-replacement.md` | prompt-only |
| `paul-once-saul.md` | ✅ |
| `peter-simon-also-called-cephas.md` | ✅ |
| `philip-the-pragmatist.md` | prompt-only |
| `simon-the-zealot.md` | prompt-only |
| `thaddaeus-judas-son-of-james.md` | prompt-only |
| `thomas-called-didymus.md` | prompt-only |

**Total:** 38 figures · **26 trained as LoRA voices** · 12 prompt-only (system-prompt-driven, no fine-tune yet — additional apostle LoRAs are on the roadmap for the next training pass).

The "trained as LoRA voice" column maps directly to the personas in the [biblical training repo](https://github.com/beaudamore/biblical) — ✅ rows have a corresponding entry in `biblical/data/source-clean/full_biblical_data/<persona>.txt` and contributed Q&A + continuation training data.

## How a prompt becomes a live persona

1. **Author the prompt** here (`*.md`).
2. **Register as an Open WebUI model** in the chat.crossandfaith.com admin UI — paste the file content as the system prompt, set the base model (Qwen3-14B + biblical LoRA for trained voices, base Qwen3-14B for prompt-only voices), tag the model with `biblical` plus `old-testament` / `new-testament` / `apostles`.
3. **The Circle of Speakers pipeline** auto-discovers it next request — no code change needed. The `SPEAKER_TAGS` filter on each circle (e.g., `biblical_circle.py` filters to `biblical`) controls participation.

This decoupling means new figures can be added in production without code deploys.
