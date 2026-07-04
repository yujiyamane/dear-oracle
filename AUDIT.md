# Session-Handoff Infrastructure Audit

**Date:** 2026-07-04 · **Scope:** read-only inventory before any Layer 0 implementation · **Auditor:** Claude Code

---

## 1. Inventory

| Location | Exists | State |
|---|---|---|
| `~/.claude/CLAUDE.md` § Session handoff | ✅ | 2 lines (header + 1 body line), lines 20–21 of a 25-line file. Quoted verbatim in §1.1 |
| `~/.claude/skills/git-session-handoff/` | ✅ | 2 files: `SKILL.md` (10,965 B, modified **2026-07-04 20:27**), `examples/worked-examples.md` (4,161 B, 2026-07-04 20:07) |
| `~/.claude/commands/` | ✅ | 4 files: `checkpoint.md`, `close.md`, `role-review.md`, `sentinel.md` |
| `~/.claude/handoff.md` | ✅ | 1,595 B, last modified **2026-06-28 12:31** — 6 days stale, NOT cleared |
| `~/.claude/settings.json` | ✅ | Extensive hooks (GSD + pixel-agents + rtk) — none session-handoff-related. See §1.5 |
| `Life/.claude/settings.json` | ✅ | One `SessionStart` hook → `$CLAUDE_PROJECT_DIR/.claude/hooks/session-start.sh` |
| `Life/.claude/settings.local.json` | ✅ | Permissions only (notion-search allow) |
| `dear-oracle/.claude/settings.json` (+ .local) | ❌ | Not found |
| `Life\dawn-patrol\git-session-handoff-spec-v1.3.md` | ❌ at that path | **Relocated** to `Life\04_projects\git-session-handoff\git-session-handoff-spec-v1.3.md` (40,373 B, 2026-06-05) during the life-cleanup restructure. dawn-patrol itself now lives under `05_systems\` |
| Any v1.4 / v1.4.1 spec | ❌ | Recursive search of Life (depth 5) for `*v1.4*` and `*session-handoff-spec*`: **only v1.3 exists** |

### 1.1 CLAUDE.md block (verbatim, 2 lines)

```
## Session handoff
First message empty, a greeting, or `/session-start` → follow the **git-session-handoff** skill's Session Brief. ANY actionable request skips the handoff — the request always wins. ALL commits follow that skill.
```

### 1.2 SKILL.md frontmatter (verbatim)

```yaml
---
name: git-session-handoff
description: >
  Use at session start, before any git commit, at checkpoint or session end,
  when writing a commit message, or on handoff. Also use for session triage,
  commit formatting, or Notion promotion from git. セッション開始・終了・
  チェックポイント・コミット・引き継ぎ時に使用。
---
```

### 1.3 Command file existence check

| Command | Exists in `~/.claude/commands/` |
|---|---|
| `session-start` | ❌ (referenced by CLAUDE.md as `/session-start` — **dangling reference**; handled by skill auto-fire, no command file) |
| `checkpoint` | ✅ (553 B, identical to project-repo copy) |
| `session-end` | ❌ (renamed → `close` post-spec) |
| `close` | ✅ (3,911 B, modified 2026-07-04 20:06 — **diverged** from project-repo copy, 2,576 B / 2026-06-06) |
| `refresh` | ❌ (exists nowhere; not in spec v1.3 either) |

### 1.4 handoff.md current content (summary)

Written 2026-06-28 by `/close`. Topic: DK/DO token rotation (cb4d30b) and the do_hits.json `meta`-wrapper rendering bug. Content is now **obsolete** — the meta-wrapper work shipped (see dear-oracle commits 7c6a9a1 … 25f91ea). Per skill, notes >24 h old are skipped, but the file should have been **read-and-cleared** on the next session start; it persists → the clear step is not executing.

### 1.5 Hooks blocks

- `~/.claude/settings.json`: SessionStart ×3 (gsd-check-update.js, gsd-session-state.sh, pixel-agents claude-hook.js), PreToolUse ×6 (rtk, gsd-prompt/read/workflow-guard, gsd-validate-commit, pixel-agents), PostToolUse ×4 (gsd-context-monitor, gsd-read-injection-scanner, gsd-phase-boundary, pixel-agents), plus pixel-agents on SessionEnd/Stop/Notification/UserPromptSubmit/PermissionRequest/PostToolUseFailure/SubagentStart/SubagentStop.
- `Life/.claude/settings.json`: SessionStart → `.claude/hooks/session-start.sh`.
- **Zero hooks belong to git-session-handoff** — consistent with spec v1.3 §2.2 "No hooks" constraint. Note `gsd-validate-commit.sh` (PreToolUse on Bash) may already inspect git commits — any Layer 0 commit-validation hook would double up with it.

---

## 2. Adherence check — `git log -5` on Life repo

Commits f3fe769, 4deaaee, bf08449, 5a4141d, 2d8f91a (all life-cleanup restructure batches):

| Criterion | Result |
|---|---|
| Conventional type prefix (`refactor:`/`chore:`) | ✅ 5/5 |
| ✅ Completed section present | ✅ 5/5 |
| ➡️ Next section present | ✅ 5/5 |
| 🚧 In Progress when applicable | ✅ 3/5 (omitted in 2 where nothing partial — permitted) |
| ❌ Failed | Omitted in all 5 (permitted when nothing failed) |
| 【label】 tag on every item | ✅ 100% (【life-cleanup】【discord-retire】【polish-retire】) |
| ➡️ items actionable by a fresh session | ✅ (concrete: task names, paths, batch numbers) |
| Max-items limits (✅≤5, 🚧≤3, ➡️≤5) | ✅ all within budget |

**Verdict: convention adherence is strong.** The only operational gap is the handoff.md read-and-clear (§1.4).

---

## 3. Discrepancies — spec v1.3 (and referenced v1.4.1) vs installed reality

1. **No v1.4/v1.4.1 spec exists anywhere.** Anything "described in v1.4.1" is undocumented on disk; v1.3 (2026-06-05, marked *Final*) is the only spec. The installed skill has evolved past it with no spec update.
2. **Spec path stale.** Spec lives at `Life\04_projects\git-session-handoff\`, not `Life\dawn-patrol\`. Update any references.
3. **Command set diverges from spec §11.4.** Spec mandates `session-start.md`, `checkpoint.md`, `session-end.md`. Installed: `checkpoint.md`, `close.md`. `session-end` was renamed `close`; `session-start.md` was never created (or removed) — yet global CLAUDE.md still says `/session-start`, a dangling command reference.
4. **handoff.md contradicts spec v1.3 §2.2.** The spec explicitly rejects handoff.md ("creates maintenance burden and divergence risk"); the installed skill and `/close` now mandate writing `~/.claude/handoff.md`. This is the largest undocumented post-v1.3 change — exactly what a v1.4 spec should have captured.
5. **"No session-start commit" is post-spec.** Installed SKILL.md retains the `--invert-grep` filter "for backward compatibility", confirming session-start commits existed in v1.3 and were later dropped — again undocumented.
6. **Project repo copy is stale (divergence risk realised).** Installed SKILL.md (10,965 B) and close.md (3,911 B) were edited **today (2026-07-04 20:06–20:27)**; the `04_projects\git-session-handoff\` public-repo copies are frozen at 2026-06-06 (8,104 B / 2,576 B). Only checkpoint.md is identical.
7. **CLAUDE.md lacks the spec's `REQUIRED:` auto-fire wording** (§3.3 mitigation for risk 1). Current 2-line block is softer than spec mandates — though §2 shows adherence is holding anyway.
8. **handoff.md read-and-clear not operating** — 6-day-old note still present (§1.4).

---

## 4. Layer 0 merge verdict

**CONDITIONALLY SAFE** — no blocking conflicts, but four naming collisions must be resolved by design, not discovered at install time:

| Collision | Detail | Required handling |
|---|---|---|
| `/checkpoint`, `/close` | Command files already exist and were hand-edited today | Layer 0 must not blind-overwrite; diff-and-merge or version-stamp |
| `session-start` name | (a) dangling `/session-start` in global CLAUDE.md, (b) Life project hook `.claude/hooks/session-start.sh`, (c) skill triggers on `/session-start` per CLAUDE.md | Pick one canonical meaning; fix the dangling reference either way |
| `~/.claude/handoff.md` | Live artefact of current `/close` flow (currently stale-but-present) | Layer 0 must adopt the same read-and-clear contract or migrate it; also fix the clear step |
| `SessionStart` hook slot | Already 3 global hooks + 1 Life project hook; spec v1.3 forbids handoff hooks; `gsd-validate-commit.sh` already guards `git commit` on PreToolUse | If Layer 0 adds hooks it breaks the v1.3 constraint and stacks on a busy event — justify explicitly in a written v1.4 spec first |

**Recommended pre-merge actions (in order):**
1. Write the missing v1.4 spec (or changelog appendix) capturing: session-end→close rename, session-start commit removal, handoff.md adoption — so Layer 0 targets documented reality, not v1.3.
2. Sync `04_projects\git-session-handoff\` from the installed copies (today's edits are unversioned in the public repo).
3. Fix the handoff.md clear step and the `/session-start` dangling reference.
