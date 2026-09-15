# Create example: level 95 Gemling Legionnaire / Twister

[简体中文](create-latest.zh-CN.md) · [Back to the project](../README.md)

This is the **latest Create design record** found in the local run directories as of 2026-09-16. The run started on 2026-09-11 at 13:13 UTC. It has not delivered a final build; this page presents the recorded design and actual progress.

## Target and design

| Field | Recorded target |
| --- | --- |
| Level | 95 |
| Class / ascendancy | Mercenary / Gemling Legionnaire |
| Main skill | Twister |
| Target game patch | 0.5.5 |
| Intended output | One endgame build and local PoB files |

The design uses **Whirling Slash to prepare Whirlwind, followed by Twister interacting with it to deal damage**. Equipment and passive choices support elemental spear attacks, attack speed, and projectiles. The boss sequence establishes the setup before entering the damage window.

The design also records that whirlwind movement, target movement, contact duration, and repeated hits affect actual output. An ordinary weapon damage readout cannot stand in for the build's total combat DPS.

## What was completed

- A mechanism design and its validation record were saved.
- A draft validation record was saved for the exact output skill **Twister** at 13:29 UTC on 2026-09-11.
- The design disclosed a gap between the target patch, 0.5.5, and the PoB 0.5.4 certification used at that time.

## What remains incomplete

The run directory has no formal Judge evaluation receipt, final artifact selection, or completed final Review receipt. No final build artifact was found for this run. Its saved state is still `active`; that does not mean generation is continuing in the background.

This is a **design-process example**, not a validated final build, a current-patch recommendation, or a performance benchmark. A complete output showcase requires a completed Create run with its final delivery summary and verification status.

## Example request

This prompt is reconstructed from the recorded target; it is not a verbatim transcript:

```text
Use /poe-bd-create to make a level 95 Gemling Legionnaire Twister build.
Target endgame mapping and bosses. Explain preparation, the combat loop,
resource recovery, and defenses. Export local PoB files and identify
mechanics that remain unverified.
```
