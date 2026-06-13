# Dear Oracle — brand.md (the palette, single source of truth)

> Every HTML/SVG surface in Dear Oracle — the morning letter, the doGet renderer,
> the "Where things stand" standings table, and the Phase-2 demo deck — reads its
> colours from THIS file. Do not hardcode colours elsewhere; if a value changes,
> change it here once.
>
> These are the standard palette values shared across all of the author's brands
> (pbi-ai-skills, Dawn Patrol, Dear Keyperson, Dear Oracle) — identical hex values
> for a consistent identity. OSS users swap this file to rebrand in one place.

## Core palette (one colour, one meaning)

| Token         | Hex       | Use |
|---------------|-----------|-----|
| Charcoal Blue | `#264653` | Letter header band, primary structure, headings on light |
| Verdigris     | `#2A9D8F` | Probability bars, primary accent, links |
| Jasmine       | `#E9C46A` | Header subtitle, secondary accent, highlights |
| Sandy Brown   | `#F4A261` | Scenario stage 1 (immediate impact) accent |
| Burnt Peach   | `#E76F51` | Scenario stage 2 (downstream effect) accent |

## Semantic signal colours (separate ramp — never reuse the core palette for these)

| Token   | Hex       | Meaning |
|---------|-----------|---------|
| up      | `#2D8659` | probability rose (▲ +Npp) |
| down    | `#C0392B` | probability fell (▼ -Npp) |
| neutral | `#8FA3AC` | no significant change (—) |

Rule: one colour carries exactly one meaning. The core palette is identity;
the semantic ramp is data. Do not colour a Δ chip with Verdigris, and do not
use `up`/`down` green/red for decorative accents.

## Letter element mapping (the contract prompts/letter.md renders to)

- Header band background: Charcoal Blue `#264653`; subtitle text: Jasmine `#E9C46A`.
- "Dear {name}," — serif face on the Charcoal Blue band.
- Probability bars (Predictor block + standings): Verdigris `#2A9D8F` fill on a
  neutral track.
- Δ chips everywhere: up `#2D8659` / down `#C0392B` / neutral `#8FA3AC`.
- Scenario blocks: stage 1 left-border Sandy Brown `#F4A261`; stage 2 left-border
  Burnt Peach `#E76F51` (depth encoded by warmth).
- Coverage-transition note (dormant→active): a light Verdigris tint background.
- Footer: muted/neutral text only.

## Usage notes

- Letter HTML uses **inline CSS only** (email clients strip `<style>`); SMTP inline
  delivery depends on this.
- doGet-rendered pages may use a `<style>` block (full browser) but must draw the
  same values from this table.
- Single-sided borders (the scenario left-borders) use `border-radius: 0`.
- Text on a coloured fill uses the darkest shade of that same family, never plain
  black or grey.

---
*v1.0 — 2026-06-13. The one place colour is defined. D45.*
