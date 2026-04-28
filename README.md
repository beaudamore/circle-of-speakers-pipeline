# Circle of Speakers — Multi-Persona Open WebUI Pipeline

[![Live](https://img.shields.io/badge/live-chat.crossandfaith.com-2d6a2d)](https://chat.crossandfaith.com)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Open WebUI](https://img.shields.io/badge/runs%20on-Open%20WebUI-orange)](https://openwebui.com)

A streaming Open WebUI **pipeline** that turns any tagged set of Open WebUI models into a **multi-speaker conversation** — one prompt, multiple distinct voices answering in turn, with intelligent ordering, dynamic introductions, and user-profile-aware response prefixes.

> 🚀 **Live in production:** [chat.crossandfaith.com](https://chat.crossandfaith.com) — sign in with Google, pick the `Biblical Circle` model, ask a question and watch the chosen biblical figures answer one after another in their own KJV-grounded voices.
>
> Background and architecture writeup: [damore.ai/blog/dynamic-circle-of-speakers-v2](https://www.damore.ai/blog/dynamic-circle-of-speakers-v2)

---

## What you get

- **One pipeline file per circle** — `biblical_circle.py`, `dynamic_circle.py`, `stoic_circle.py`, `hr_circle.py`, `legal_circle.py`. Each is a tiny ~100-line shim that sets `SPEAKER_TAGS` and inherits from the shared blueprint.
- **The shared `circle_of_speakers_blueprint.py`** (~1300 lines) does the heavy lifting:
  - Discovers Open WebUI models tagged for the circle
  - Asks an **"Intelligent Speaker Ordering"** model who should respond next, given recent conversation context
  - Streams each chosen speaker's response in turn through Open WebUI
  - Injects a one-time introduction the first time each speaker appears
  - Personalizes responses by extracting profile info from the user's system prompt
- **38 ready-to-use biblical speaker prompts** (21 Old Testament + 2 NT non-apostles + 15 apostles) — drop-in system prompts for Open WebUI models, see [`prompts/biblical/`](prompts/biblical/).
- **Production-tested** — running 24/7 at [chat.crossandfaith.com](https://chat.crossandfaith.com) for weeks of real user traffic.

---

## How it works

```mermaid
flowchart LR
    U[User] --> OW[Open WebUI]
    OW --> P["Pipelines container<br/>(Open WebUI 'pipelines' addon)"]
    P --> C["biblical_circle.py<br/>(or stoic, hr, legal, dynamic)"]
    C --> B["circle_of_speakers_blueprint.py"]
    B --> R["Speaker registry<br/>(filtered by SPEAKER_TAGS)"]
    B --> O["Intelligent Speaker<br/>Ordering model"]
    O --> B
    B --> S1["Speaker 1<br/>(Open WebUI model)"]
    B --> S2["Speaker 2<br/>(Open WebUI model)"]
    B --> S3["Speaker N<br/>(Open WebUI model)"]
    S1 --> P
    S2 --> P
    S3 --> P
    P --> OW
    OW --> U
```

Each "speaker" is just an Open WebUI model — could be a base model with a system prompt, a fine-tuned LoRA, or any other registered model. The blueprint filters which ones participate in a given circle by tag (`biblical`, `stoic`, etc.) and lets the **Intelligent Speaker Ordering** model decide who responds next based on the conversation so far.

---

## Quick start

### Prerequisites

- A running [Open WebUI](https://openwebui.com) instance with the **Pipelines** addon enabled.
- One or more registered Open WebUI models tagged for your circle (e.g., tag = `biblical`).
- An "Intelligent Speaker Ordering" model registered in Open WebUI — any chat model with the system prompt from [`prompts/base/intelligent_speaker_ordering.md`](prompts/base/intelligent_speaker_ordering.md).

### Install a circle

1. Drop the desired circle file into your Pipelines container's `pipelines/` directory:

   ```sh
   cp pipelines/biblical_circle.py /path/to/openwebui/pipelines/
   ```

2. Drop the shared blueprint into the path the circle imports from. The default is `/app/blueprints` inside the Pipelines container — mount or copy:

   ```sh
   cp pipelines/blueprints/*.py /path/to/openwebui/blueprints/
   ```

3. Open WebUI auto-reloads pipelines on file change. The new `Biblical Circle` (or whichever) will appear as a model in the model picker.

4. Open the model's valves in the Open WebUI admin UI:
   - `OPENWEBUI_ENDPOINT` → your Open WebUI URL (default `http://host.docker.internal:3000`)
   - `OPENWEBUI_API_KEY` → a JWT token from an Open WebUI admin user
   - `SPEAKER_TAGS` → the tag(s) you assigned to circle-eligible models (default for `biblical_circle.py` is `biblical`)

That's it. Send a message and the circle responds.

### Add a new persona to an existing circle

1. Register a new Open WebUI model (any base + system prompt, or fine-tuned LoRA).
2. Tag it with the circle's tag (`biblical`, `stoic`, etc.).
3. Open WebUI tells the pipeline about it on the next request — no code change.

This is the architectural decoupling that makes the pipeline persona-agnostic. Change the tag set, get a different circle.

---

## Available circles

| Pipeline | `SPEAKER_TAGS` | Use case |
| --- | --- | --- |
| `biblical_circle.py` | `biblical` | Biblical figures only — what powers chat.crossandfaith.com |
| `stoic_circle.py` | `stoic` | Stoic philosophers (Marcus Aurelius, Seneca, Epictetus, …) |
| `hr_circle.py` | `hr` | Workplace / HR personas |
| `legal_circle.py` | `legal` | Legal advisor personas |
| `dynamic_circle.py` | (configurable) | The base, no fixed tag — set tags in valves |

All five are 100-line subclasses of [`pipelines/blueprints/circle_of_speakers_blueprint.py`](pipelines/blueprints/circle_of_speakers_blueprint.py). Adding a new circle is three lines: subclass, set `SPEAKER_TAGS`, save.

---

## The 38 biblical speakers

See [`prompts/biblical/README.md`](prompts/biblical/README.md) for the full roster.

```text
prompts/biblical/
├── old-testament/          21 figures (Amos, Daniel, David, ... Zephaniah)
└── new-testament/
    ├── james-the-brother-of-jesus.md
    ├── jude-contender-for-the-faith.md
    └── apostles/           15 figures (the 12 + Paul + Barnabas + Matthias)
```

**26 of these are also fine-tuned LoRA voices** trained on KJV per-persona corpora; the model layer (separate work) lives at [`github.com/beaudamore/biblical`](https://github.com/beaudamore/biblical). The remaining 12 apostle prompts run as system-prompt-driven personas on the base model and are slated for future fine-tuning.

---

## Configuration cheat sheet

The full set of valves is documented inline in [`pipelines/blueprints/circle_of_speakers_blueprint.py`](pipelines/blueprints/circle_of_speakers_blueprint.py). The most-touched ones:

| Valve | Default | What it does |
| --- | --- | --- |
| `SPEAKER_TAGS` | `""` (set per circle) | Comma = OR, plus = AND. Filters the model registry. |
| `ORCHESTRATION_MODEL_NAME` | `Intelligent Speaker Ordering` | The Open WebUI model that decides turn order. |
| `DECISION_CONTEXT_DEPTH` | `4` | How many recent rounds the orderer sees. |
| `ENABLE_DYNAMIC_INTRODUCTIONS` | `true` | One-time intro the first time each speaker appears in a conversation. |
| `ENABLE_USER_PROFILE_INTEGRATION` | `true` | Extracts personal info from the user's system prompt and weaves it into responses. |
| `PROFILE_THUMBNAIL_ROOT` | `https://images.crossandfaith.com/image/` | Per-speaker avatar source. Replace with your own. |
| `enable_full_debug` / `enable_step_debug` | `false` | Verbose logging while you're tuning. |

---

## Project structure

```text
.
├── README.md
├── LICENSE
├── pipelines/
│   ├── blueprints/
│   │   ├── circle_of_speakers_blueprint.py    The reusable base
│   │   └── openwebui_streaming_blueprint.py   Lower-level streaming utilities
│   ├── biblical_circle.py
│   ├── dynamic_circle.py
│   ├── hr_circle.py
│   ├── legal_circle.py
│   └── stoic_circle.py
└── prompts/
    ├── base/                                  Speaker-ordering + pipeline prompts
    ├── biblical/                              38 biblical figures
    └── shakespeare/
```

---

## Production context

The pipeline is one piece of a larger production stack at [chat.crossandfaith.com](https://chat.crossandfaith.com): it sits between Open WebUI and a vLLM server hosting **Qwen3-14B** with hot-swapped LoRA adapters (biblical / augustine / liguori). The runtime fronts a 17-container deployment with Postgres, encrypted-at-rest storage, Cloudflare TLS, Trivy vulnerability scanning, and SOC 2 Type II policy coverage.

Detailed writeup: [damore.ai/blog/dynamic-circle-of-speakers-v2](https://www.damore.ai/blog/dynamic-circle-of-speakers-v2)

---

## Related projects

- **Model layer (LoRA adapters):** [github.com/beaudamore/biblical](https://github.com/beaudamore/biblical) — the fine-tuning pipeline that produces the 26 biblical voices.
- **Live deployment:** [chat.crossandfaith.com](https://chat.crossandfaith.com)
- **Project blog:** [damore.ai/blog](https://www.damore.ai/blog)
- **Open WebUI:** [openwebui.com](https://openwebui.com)

---

## Author

Built by [Beau D'Amore](https://damore.ai) — AI Solutions Architect specializing in OpenWebUI, vLLM, LLM fine-tuning, and private AI infrastructure.

- 🌐 [damore.ai](https://www.damore.ai)
- 💬 [chat.crossandfaith.com](https://chat.crossandfaith.com) (live demo)
- 🐙 [github.com/beaudamore](https://github.com/beaudamore)
- 💼 [linkedin.com/in/beaudamore](https://linkedin.com/in/beaudamore)
