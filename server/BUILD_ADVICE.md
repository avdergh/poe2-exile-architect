# Path of Exile 2 — build-optimization principles

Durable planning heuristics for making a PoE2 build stronger. They are not a meta list or
versioned mechanical authority. **For patch-sensitive facts, the current pinned PoB data,
physical graph, and current corpus take precedence over this prose.** The engine computes your
build's actual numbers; use these rules to decide *what* to change, then verify the effect.
Never quote a DPS/EHP/resist figure you didn't get from a compute tool.

## The optimization loop

Always **create → validate → cost → present**. Make one change at a time, recompute on the
engine (`get_build_stats` / `get_defenses`), and keep it only if it improves the goal. Use
`compare_to` for A/B deltas. A build that fails `evaluate_build` is flagged, not recommended.
Optimization is finding the build's *weakest layer* and spending the cheapest points/currency to
raise it — not maximizing the number that's already highest.

**Min/maxing a complete build** is the same loop pointed at marginal gain: once defense is
complete and resists are capped, find where the *next* point/currency pays most rather than
guessing. `rank_levers` measures each candidate stat's real Δ on the current build and ranks
them, so you spend on the lever that actually moves the number (often penetration or attack/cast
speed over raw "increased" damage). For concrete moves rather than abstract stats, `rank_upgrades`
ranks which gear slot recrafts for the most gain, and `plan_gear` re-plans the whole set with
resists kept capped. Confirm the magnitude with `solve_for`, apply the real gear/tree change, then
re-verify defense — a min/maxed build never trades back below the "done" bar.

## What "done" looks like — targets, not vibes

A build is a **draft** until it clears this bar. Don't present one as finished until it does
(check with `get_defenses` + `evaluate_build`):

- **Resistances capped.** Fire/Cold/Lightning at 75% (over-cap is buffer); chaos positive. Non-negotiable.
- **A full gear set.** Every slot filled — weapon(s), helmet, body, gloves, boots, belt, amulet,
  two rings. A build with 2 of ~10 slots is a *skeleton*, not a build.
- **A real hit pool.** A meaningful Life and/or ES pool — thousands for endgame, not the few
  hundred a fresh character starts with.
- **Enough DPS for the target content.** "Enough" is relative: mapping needs far less than
  pinnacle bosses. The test is *time-to-kill on the content the player wants*, not a fixed number.
  If unsure, ask what content they're aiming at, or compare against a known-good reference build.
- **Sustain.** The build can actually use its skill (mana/spirit covered by pool + regen/leech),
  with recovery beyond flasks.

**Reality check:** a from-scratch build with one weapon, a couple of notables, uncapped resists,
and a few-hundred life pool is a skeleton that validates the *workflow* — it is **not** finished,
and it's typically *orders of magnitude* behind a min-maxed meta build (DPS and EHP). Say so
plainly; never present a skeleton as "done".

---

## Reaching endgame DPS (orders of magnitude, not increments)

Endgame content assumes very high DPS. If a build is far short, the fix is usually a **missing
core multiplier**, not more small increases. Work in this order:

1. **Find THIS build's dominant multiplier and verify it with `rank_levers` — don't assume.**
   Archetypes scale on different things; measure, don't reach for a favorite. The dominant lever
   varies: it might be **crit** (chance × multi can be 3–7× — a meta crit nuke can run ~98% crit / 7× multi), a big
   **"more"-multiplier** support stack, **ailment/DoT** (poison/ignite/bleed, or shock far exceeding
   its 20% base), **minions**, **"+levels to skills"**, or **penetration/exposure**. There's no
   universal answer — crit and mana-stacking are each just *one* option. Put whatever `rank_levers`
   says dominates in *before* fine-tuning gear; look the skill up if unsure (`explain_mechanic`).
   **Allocate the ascendancy early — its notables are often the biggest single multiplier** (a
   conditional "more vs bosses/rares" can be +50%). A *conditional* "more" stays invisible in the
   DPS read until you switch on its enemy-condition (`apply_combat_profile`, or `set_config` from
   `list_config_options` — e.g. Open Weakness, Critical Weakness), so allocate it AND enable the
   condition the build genuinely applies.
2. **Pick ONE scaling identity and commit fully.** Either crit (commit to *both* chance and multi +
   a *base*-crit source — half-invested crit is wasted, and "increased" crit does nothing from zero)
   OR a non-crit lane (a "more"-multiplier stack, ailment/DoT, or minions). Don't half-do crit, and
   don't bolt crit onto a skill/ascendancy that doesn't support it. Which lane is right depends on
   the skill, ascendancy, and goal — not a default.
3. **Match the skill to the goal — boss vs farm are often different skills.** A slow, high-damage
   nuke (sometimes triggered by a crit/ailment trigger meta-gem) tends to be the single-target BOSS
   engine; a fast multi-projectile or wide-AoE skill tends to be the CLEAR/farm engine. Don't
   optimize the clear skill for boss DPS — strong setups often run a different skill for each. The
   right skill is the player's call (or their stated goal); don't default to a particular one.
4. **Stack the build's defining resource.** For a crit caster that's crit + the hit's base damage +
   cast rate; for a mana-stacker it's ES/mana via **Eldritch Battery + Mind over Matter** (one stat
   becomes both damage *and* EHP). Mana-stacking is ONE layer, **not automatically the master
   lever** — `rank_levers` tells you which actually moves *this* build.
5. **Don't skip jewels — or build-defining UNIQUES.** Real endgame builds run **8–10 jewels**,
   including unique/radius jewels (e.g. Time-Lost series) that supply passive/notable density —
   that's often why a meta tree reads "over budget". Craft rare jewels with
   `optimize_jewel`; socket via `equip_jewel` (`list_jewel_sockets`) and rank radius jewels by
   socket with `evaluate_jewel_socket`. More broadly, a pile of
   self-crafted RARES is the **from-scratch ceiling** (~100k) — the leap to pinnacle usually comes
   from a **build-defining unique** (extra projectiles, "+levels to skills", a converted/enabled
   mechanic) that rares simply can't roll. Use **`relevant_uniques`** to surface the uniques + unique
   jewels that match the active build's scaling, read the full text (`get_unique`), then `equip_item`
   / `equip_jewel` and **measure the delta on the engine** — uniques ENABLE mechanics, so verify, and
   never quote their power from the corpus text.
6. **Re-verify defense after each big swing.** Resists drift and silently break caps when you
   reshuffle gear for damage — re-check `get_defenses` every time.

A useful sanity check: realistic gear should reach high six figures on a strong archetype; if the
engine shows far less, suspect either a missing core multiplier (above) or that a mechanic isn't
being modeled — note the latter rather than trusting the low number.

**Know what the engine can and can't model — and choose a modellable archetype.** The pinned PoB
computes hits, ailments, auras, and supports faithfully, but it does **NOT** yet model **energy-based
meta TRIGGERS** — Cast on Critical and the Invocation / Spell-on-Hit gems. A spell socketed into one
computes as a weak **self-cast**, never the triggered nuke it is in game; the tools flag this as
`engineLimitation` in their output. So the famous **Cast-on-Critical → Comet** pinnacle setup (and
similar trigger-meta builds) **can't be honestly costed here yet** — never present a triggered
skill's self-cast number as its real DPS. When the goal points at a trigger-meta archetype, say the
engine can't model it yet and steer to one it CAN: a **directly cast/attacked** crit skill, an
ailment/DoT, minions, or a "more"/penetration stack all compute faithfully and reach pinnacle DPS.

**A multiplier reads weak until it's fully assembled.** Crit chance especially: "% increased" only
scales a low base (~5–10%), so increased alone caps far short of the ~90%+ a nuke wants — real crit
comes from **flat "+to Critical Hit Chance", a high-base-crit weapon/skill, or an ascendancy crit
ENGINE** (e.g. an accuracy→crit conversion — which can have steep diminishing returns, so verify it
on the engine, don't assume it scales linearly). Because a half-built multiplier reads weak *per
slot*, judge crit (or any "more" lane) once it's **committed across the whole build** — tree plus
several gear slots together — not from one slot's marginal Δ. Greedy per-slot tuning systematically
under-rates a lane you're still assembling, which is why reaching pinnacle takes a deliberate
archetype commitment, not slot-by-slot hill-climbing.

**Measure the right number, with the fight realistic.** For multi-projectile/multi-hit skills read
**FullDPS** alongside `TotalDPS`. PoB defines `TotalDPS` as Hit DPS, while `FullDPS` rolls up the
included skill actors and DoT components. Their difference is not automatically a lower/upper-bound
interval: real single-target damage depends on uptime, rotation and per-skill projectile overlap.
Verify the specific skill (`explain_mechanic`/`lookup_mechanic`/in-game) and compare like-for-like.
Full-text mechanic hits are candidates only: read the selected exact page and judge whether its
content actually supports the claim before using it.
The engine's enemy
conditions are **off by default**, so a bare stat read understates a real fight: use
`apply_combat_profile` to switch on the shock/curse/charges/boss-tier the build actually maintains
before judging DPS (turn off any it can't sustain — they'd inflate the number). The mana *pool*
isn't automatically the master lever: some real meta million-DPS builds run only ~6–8k mana and get
most of their damage from **crit + the hit + chase jewels**, not pool size — but that's *those*
builds, not a rule (ailment/DoT/minion builds scale elsewhere). Never assume one recipe; let
`rank_levers` find what actually moves *this* build.
**To chase a specific meta build, import its PoB** (`import_build`) and read its keystones, crit,
skill (including any trigger/meta-gem), and jewels — then build to that archetype and verify
each layer on the engine; `compare_to` shows the per-stat gap. When the build looks done, gate it
with `pinnacle_readiness` (resists + chaos + EHP + DPS) — note real ~1M-DPS builds run only
~17–20k EHP and survive on Mageblood + charms + dodge, so breadth/recovery beats a huge pool.

## What verified endgame builds scale on — calibrate, don't copy

Distilled from a diverse set of engine-VERIFIED high-end builds (the reference library:
`list_reference_builds` / `benchmark_build`). These describe *how strong builds scale*, not *what to
play* — they name no skill on purpose. Reference builds are **calibration only**: use them to
range-check a number and spot the dominant lever; never copy or recommend one wholesale — build to
the player's stated goal.

- **"+levels to skills" is the universal #1 damage lever.** Across every computable reference build —
  spell, attack, projectile, minion, and ailment alike — the highest-value marginal lever is *+to
  Level of all (relevant) Skills*. Chase it first and from every source (gem level/quality, `+to
  Level of all [type] Skills` on weapon/amulet/focus, level-granting uniques/supports), then
  fine-tune. Confirm with `rank_levers`; a *high* marginal % there means it's still under-invested
  (headroom), not that it stopped mattering.
- **The rest of the hierarchy is stable:** after +levels → **penetration/exposure** (once you've
  committed to one element vs resistant bosses) → **"more" multipliers** (supports; ~1:1 with DPS) →
  **flat `+%` critical damage bonus** (broadly useful even on "non-crit" builds) → **rate**
  (attack-speed XOR cast-speed, whichever the skill uses). *"Increased" damage is near the bottom on
  a finished build* — it diminishes fast; spend on the multipliers above it.
- **Defense = convert one resource into both damage and EHP.** Strong builds pick one identity and
  commit: **ES via Chaos Inoculation** (life→1; immune to chaos damage and Bleeding in the current
  0.5 tree; tankiest, can exceed 30k EHP), **mana via Eldritch Battery + Mind over Matter** (mana is
  the hit-buffer and often the damage), or **life + Mind over Matter**. Plain life/ES hybrid is fine
  for attack builds. Pick one and stop paying for the stats it doesn't use.
- **The verified endgame bar:** finished single-target builds cluster around **~1M+ DPS** (≈1M–6M) at
  **~20–35k EHP** (CI/ES stackers higher), resists capped, chaos handled (capped or CI). Most run
  modest pools + recovery + dodge, not a huge HP bar. Use `benchmark_build` to see where the active
  build sits; if it's an order of magnitude short, a *multiplier* is missing (above), not margins.

## Defense: the survival checklist

Survivability is **layered**: avoidance × mitigation × hit-pool × recovery, plus ailment and
stun protection. A weakness in any one layer is what actually kills you, so breadth beats
over-stacking one stat.

1. **Cap elemental resistances at 75% — this is non-negotiable.** Maps are balanced around it.
   Uncapped resist isn't "less reduction," it's *more damage taken*: at 50% fire res you take
   **twice** the fire damage of someone at 75%. The campaign applies a stacking area penalty
   (−10% per act, ending around −60% at endgame), so you must gear ~+125–150% elemental res to
   sit at the cap. **Chaos resistance** has its own 75% cap and no area penalty, but its opportunity
   cost is stage-dependent: get it non-negative for campaign completion, build toward roughly
   20–40% in early maps, and pursue 60–75% only when endgame content, the defensive identity, or
   available suffix budget justifies it. Do not sacrifice core damage, resource sustain, movement,
   or required attributes merely to make every resistance read 75%.
2. **Run at least one mitigation/avoidance layer, and know its weakness:**
   - **Armour** reduces hit damage on a curve — roughly `reduction = Armour / (Armour + 12 ×
     hit)`, capping near 90%. It's excellent against many small hits and **weak against single
     big hits** (a hit large enough relative to your armour barely gets reduced). Don't rely on
     armour alone to survive one-shots.
   - **Evasion** gives a chance to avoid **strikes and projectiles** (mostly attacks). It does
     little against spells and AoE. It's entropy-based, so it's consistent against many hits but
     never a guarantee against the one that matters.
   - **Energy Shield** is an extra hit pool that **recharges** after a short delay without
     damage — great when you can avoid sustained damage. Without a relevant immunity, **chaos
     damage is twice as effective against ES**, while **bleed and poison bypass ES**; **stun
     ignores ES by default** (scale stun threshold if you go heavy ES). Current 0.5
     `Chaos Inoculation` is the important exception: it grants immunity to chaos damage and
     Bleeding. Its chaos-damage immunity prevents poison damage, but does not by itself prove
     that poison cannot be applied. Evasion+ES is a strong hybrid: evasion buys the downtime ES
     needs to recharge.
3. **Build a real hit pool (EHP).** Avoidance and mitigation only matter if a pool sits behind
   them. Don't glass-cannon. Life scales with level and Strength (+2 Life per Strength); ES
   layers on top. Current 0.5 `Chaos Inoculation` (Life → 1, immune to chaos damage and
   Bleeding) only makes sense once ES is the overwhelming majority of your effective HP.
4. **Have recovery, not just a pool.** Keep life flasks upgraded, then add a sustained source:
   regen, leech, or recoup (repays a portion of a hit over 8s). ES wants faster recharge *start*
   and recharge *rate* (or convert life regen via Zealot's Oath).
5. **Defend against ailments — they're a top killer.** Capped resistances reduce the chance and
   magnitude; **ailment threshold** (scales with your pool) reduces it further; charms cleanse.
   Watch **shock** (you take ~20% more damage), **freeze** (you can't act), and, unless the
   current build is immune, **bleed** (physical DoT, *doubled while moving*).
6. **Use your active defense.** The **dodge roll** is your strongest tool — i-frames against
   strikes and projectiles (but **not** AoE). Good positioning and rolling beats raw stats.
7. **Priority order when you're short:** ① cap resistances → ② ailment defense → ③ life pool +
   recovery → ④ your main mitigation layer (armour/evasion/ES) → ⑤ supplementary (block, damage
   shifting). For *damage-taken reduction*, "reduced" (additive) is stronger than "less"
   (multiplicative).

Use `get_defenses` to read resist over-cap and EHP; the weakest of the layers above is almost
always the right place to spend next.

---

## Offense: the damage checklist

Damage is computed in this order — knowing it tells you what's worth buying:
**base → added flat → increased (additive) → more (multiplicative) → enemy mitigation
(resistance / penetration), applied last.**

1. **"More" beats "increased."** Increased modifiers add together (two +20% = ×1.4); "more"
   modifiers each multiply (two 20% more = ×1.44). Your biggest "more" multipliers come from
   **support gems** — picking the right supports is usually your largest single damage lever. The
   corpus has no support magnitudes, so let `optimize_supports` pick the best set by measuring each
   on the engine, rather than eyeballing it.
2. **Stack flat added damage early.** It sits at the bottom of the order, so every increased /
   more / crit / speed multiplier on top scales it. Early flat damage compounds as your
   multipliers grow.
3. **Mix your scaling layers.** Added + increased + more + crit + speed + penetration multiply
   together; spreading investment across several layers vastly outperforms over-investing one
   (e.g. dumping everything into "increased" hits hard diminishing returns).
4. **Crit needs both halves.** Base critical damage bonus is +100% (a crit deals ~2×). Crit
   chance and crit damage are useless without each other — balance them, don't stack one.
5. **Match the enemy's resistance and lower it.** Damage is reduced by enemy resistance last, so
   **penetration** and **exposure** (−% enemy resistance) are effectively "more" damage. Pick a
   damage type and commit; don't split across types.
6. **Respect conversion.** When a skill converts damage (e.g. physical → cold), **only modifiers
   for the final type apply.** Scaling the pre-conversion type is wasted.
7. **Hit rate is damage.** Attack/cast speed multiplies DPS directly — just budget the resource
   (mana) cost. It won't show in a single-hit tooltip; check `TotalDPS`.
8. **Read the skill's tags.** Only modifiers matching a skill's tags (Spell/Attack/Projectile/
   element/…) affect it. Off-tag stats do nothing.
9. **Gem level and quality** are cheap, durable damage — spells gain flat damage per level,
   attacks scale better with weapon damage.

---

## Spirit, links, and budget

**Spirit** is a separate resource that pays for *persistent* effects — auras/buffs, minions,
and meta/trigger gems. Treat it like a budget: spend it on the persistent effects with the
highest impact for your build, and scale it with +Spirit gear (sceptres, amulets, body armour)
when you need more reservation. Don't leave a big chunk of spirit unspent.

---

## Design patterns of strong builds

Structural patterns strong builds share — stated as durable design, **not** as any current pick
(no specific skill/item/ascendancy is "the answer"). Use them to shape a build, then verify on
the engine.

- **Defense is *completed*, not partial.** Strong builds reach a full defensive baseline before
  chasing more damage: resistances capped, a real hit pool, every gear slot used. A build with
  uncapped resists or a few-hundred pool is unfinished, however high its tooltip DPS.
- **Commit to one damage type and scale it multiplicatively.** Pick a single damage type (often a
  single ailment too) and stack it rather than splitting across types. Support gems are the
  *backbone* — most of the damage comes from the multiplicative ("more") supports on the main
  skill (`optimize_supports` finds the best set by engine-measuring each); gear and tree add
  flat/increased on top.
- **Crit is all-or-nothing.** If a build goes crit, it commits to *both* crit chance and crit
  damage (plus a crit support) — half-invested crit is wasted. Builds that don't commit scale
  hit/ailment damage instead. Pick one lane.
- **Pick one defensive archetype and let it reshape the build.** Life, energy shield, or a hybrid
  — the choice changes which stats matter. An ES-only identity such as current 0.5
  `Chaos Inoculation` (Life → 1, immune to chaos damage and Bleeding) makes life *and* chaos
  resistance irrelevant; an evasion/ES hybrid wants recharge uptime; an armour/life build wants
  flat life and big-hit mitigation. Choose, then stop paying for stats your archetype doesn't use.
- **Use every slot.** Complete builds fill gear *and* jewels, and cover ailments with charms — not
  just resistances. Empty slots and missing ailment coverage are unfinished work.
- **Solve "tax" stats on suffixes; spend prefixes on the payoff.** Resistances and attributes are
  typically suffixes, so prefixes can carry the build's defining stats (life/ES, added damage —
  the things that scale it).

None of these prescribe *what* to play — they describe what *coherent* looks like. The skill,
items, and ascendancy are the player's call; these are the structural discipline that turns any
of those choices into a working build.

## Common red flags (cheap wins hiding here)

- Uncapped elemental resistance, or negative chaos resistance.
- A single defensive layer and nothing else (e.g. big life pool, zero mitigation/avoidance).
- No recovery beyond flasks.
- No ailment-threshold or charm coverage for shock/freeze/bleed.
- Damage split across two types, or scaling a pre-conversion damage type.
- Over-investing "increased" damage while owning no "more" multipliers (supports).
- A high tooltip hit with low attack/cast speed (low sustained DPS).

When you spot one of these, it's usually the highest-return change available — propose it, then
**verify the delta on the engine** before recommending it.
