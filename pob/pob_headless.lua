-- pob_headless.lua — stdio JSON-RPC bridge to the PoB-PoE2 calculation engine.
--
-- Run with the working directory set to <repo>/pob/PathOfBuilding-PoE2/src
-- (mirrors the fork's .busted: directory=src, lpath=../runtime/lua, helper=HeadlessWrapper).
--
-- Protocol: one JSON object per line on stdin, one JSON object per line on stdout.
--   request : {"id": <n>, "method": "<name>", "params": {...}}
--   response: {"id": <n>, "ok": true,  "result": {...}}
--          or {"id": <n>, "ok": false, "error": "<message>"}
-- A startup frame {"ready": true, ...} is emitted once the engine has initialised.
-- All engine chatter is routed to stderr so stdout carries only JSON-RPC frames.

package.path = "./?.lua;./?/init.lua;../runtime/lua/?.lua;../runtime/lua/?/init.lua;" .. package.path

-- Pure-Lua stand-in for the lua-utf8 C module (ASCII-correct; see pob/PINNED.md).
package.preload["lua-utf8"] = function()
	local u = {}
	for _, k in ipairs({ "find", "gmatch", "gsub", "match", "sub", "reverse",
		"len", "char", "byte", "upper", "lower", "rep", "format" }) do
		u[k] = string[k]
	end
	u.offset = function(s, n, i) return (i or 1) + (n or 0) end
	u.next = function(s, i)
		i = (i or 0) + 1; if i > #s then return nil end; return i, s:byte(i)
	end
	u.charpos = function(s, i) return i or 1 end
	u.width = function() return 1 end
	return u
end

-- Clean RPC frames go to the real stdout; everything else is pushed to stderr.
local _stdout = io.stdout
local function emit(line)
	_stdout:write(line); _stdout:write("\n"); _stdout:flush()
end
_G.print = function(...)
	local n = select("#", ...)
	local parts = {}
	for i = 1, n do parts[i] = tostring((select(i, ...))) end
	io.stderr:write(table.concat(parts, "\t")); io.stderr:write("\n")
end
io.write = function(...) io.stderr:write(...); return io.stderr end

local json = require("dkjson")

-- Boot the engine (its prints now land on stderr).
local booted, bootErr = pcall(dofile, "HeadlessWrapper.lua")
if not booted or not build then
	emit(json.encode({ ready = false, error = "engine init failed: " .. tostring(bootErr) }))
	os.exit(1)
end

-- ---------------------------------------------------------------------------
-- helpers
-- ---------------------------------------------------------------------------
local DEFAULT_STATS = {
	"TotalDPS", "FullDPS", "CombinedDPS", "AverageDamage", "Speed", "MovementSpeedMod",
	"EffectiveMovementSpeedMod", "MovementSpeedWhileUsingSkill", "HitChance",
	"CritChance", "CritMultiplier", "ManaCost", "Life", "LifeUnreserved", "LifeReserved",
	"LifeUnreservedPercent", "Mana", "ManaUnreserved", "ManaUnreservedPercent", "EnergyShield",
	"LifeRegenRecovery", "LifeLeechGainRate",
	"LifeOnHitRate", "LifeLeechGainPerHit", "LifeRecharge", "EnergyShieldRegenRecovery",
	"EnergyShieldLeechGainRate", "EnergyShieldOnHitRate", "EnergyShieldRecharge",
	"ManaRegenRecovery", "ManaLeechGainRate", "ManaLeechGainPerHit", "ManaOnHitRate",
	"NetManaRegen", "ExtraPoints", "WeaponSetPassivePoints", "PassivePointsToWeaponSetPoints",
	"TotalEHP", "Ward", "Armour", "Evasion", "Str", "Dex", "Int", "ReqStr", "ReqDex", "ReqInt",
	"Spirit", "SpiritReserved", "SpiritUnreserved", "SpiritUnreservedPercent", "ProjectileCount",
	"EvadeChance", "MeleeEvadeChance", "ProjectileEvadeChance", "SpellEvadeChance",
	"SpellProjectileEvadeChance", "AvoidAllDamageFromHitsChance", "AvoidPhysicalDamageChance",
	"AvoidFireDamageChance", "AvoidColdDamageChance", "AvoidLightningDamageChance",
	"AvoidChaosDamageChance", "AvoidProjectilesChance", "BlockChance", "SpellBlockChance",
	"EffectiveBlockChance", "EffectiveSpellBlockChance", "EffectiveAverageBlockChance",
	"SpellSuppressionChance", "EffectiveSpellSuppressionChance",
	"MinionCombinedDPS", "MinionTotalDPS", "ActiveMinionLimit",
}

local function asNumber(v)
	if type(v) == "number" then
		return v
	elseif type(v) == "string" then
		return tonumber(v) or 0
	elseif type(v) == "boolean" then
		return v and 1 or 0
	end
	return 0
end

local function outputValue(out, key)
	out = out or {}
	local v = out[key]
	if v ~= nil then
		return v
	end
	local minion = out.Minion
	if type(minion) == "table" then
		if key == "MinionCombinedDPS" then
			return minion.CombinedDPS
		elseif key == "MinionTotalDPS" then
			return minion.TotalDPS
		elseif key == "ActiveMinionLimit" then
			return minion.ActiveMinionLimit or out.ActiveMinionLimit
		elseif minion[key] ~= nil then
			return minion[key]
		end
	end
	return nil
end

local function collectStats(keys)
	local out = (build.calcsTab and build.calcsTab.mainOutput) or {}
	local res = {}
	local list = (type(keys) == "table") and keys or DEFAULT_STATS
	for _, k in ipairs(list) do
		local v = outputValue(out, k)
		local t = type(v)
		if t == "number" or t == "string" or t == "boolean" then
			res[k] = v
		end
	end
	return res
end

-- PoE2 ascendancy point cap (a separate pool from passive points) — mirrors PoB's Build.lua ascMax.
local ASCENDANCY_POINT_MAX = 8

-- Normal passive points available at the current level: 1 per level past 1, plus the
-- cumulative quest points unlocked by that level (mirrors PoB's EstimatePlayerProgress).
local function availablePoints()
	local level = build.characterLevel or 1
	local qp = 0
	for _, act in ipairs(build.acts or {}) do
		if level >= (act.level or 1) then
			qp = act.questPoints or qp
		end
	end
	local out = (build.calcsTab and build.calcsTab.mainOutput) or {}
	return math.max(0, level - 1 + qp + asNumber(out.ExtraPoints))
end

local function skillNameAt(groupIndex, activeIndex)
	local sg = build.skillsTab.socketGroupList[groupIndex or build.mainSocketGroup or 1]
	if sg and sg.displaySkillList then
		local s = sg.displaySkillList[activeIndex or sg.mainActiveSkill or 1]
		if s and s.activeEffect and s.activeEffect.grantedEffect then
			return s.activeEffect.grantedEffect.name
		end
	end
	return nil
end

local function mainSkillName()
	return skillNameAt(build.mainSocketGroup or 1)
end

local function gemSummaryForSocketGroup(groupIndex)
	local gems = {}
	local sg = build.skillsTab.socketGroupList[groupIndex or build.mainSocketGroup or 1]
	if sg then
		for _, g in ipairs(sg.gemList or {}) do
			local nm = g.nameSpec
			if (not nm or nm == "") and g.gemData and g.gemData.grantedEffect then
				nm = g.gemData.grantedEffect.name
			end
			if nm and nm ~= "" then
				local ge = (g.gemData and g.gemData.grantedEffect) or g.grantedEffect
				local isSupport = (ge and ge.support) or (g.gemData and g.gemData.tags and g.gemData.tags.support) or false
				table.insert(gems, {
					name = nm,
					level = g.level,
					quality = g.quality,
					isSupport = isSupport and true or false,
					isActive = not isSupport,
					supportKnown = isSupport and true or false,
				})
			end
		end
	end
	return gems
end

local function sortedKeys(map)
	local out = {}
	if type(map) == "table" then
		for key, value in pairs(map) do
			if value then
				out[#out + 1] = tostring(key)
			end
		end
	end
	table.sort(out)
	return out
end

local function addUnique(list, seen, value)
	if value and value ~= "" and not seen[value] then
		seen[value] = true
		list[#list + 1] = value
	end
end

local function activeWeaponTypes(active)
	local typesByRequirement = {}
	local function addRequirement(types)
		local keys = sortedKeys(types)
		if #keys > 0 then
			typesByRequirement[#typesByRequirement + 1] = keys
		end
	end
	local ge = active and active.activeEffect and active.activeEffect.grantedEffect
	addRequirement(ge and ge.weaponTypes)
	for _, effect in ipairs((active and active.supportList) or {}) do
		local supportGe = effect and effect.grantedEffect
		if supportGe and supportGe.support and supportGe.weaponTypes then
			addRequirement(supportGe.weaponTypes)
		end
	end
	local flat, seen = {}, {}
	for _, group in ipairs(typesByRequirement) do
		for _, weaponType in ipairs(group) do
			addUnique(flat, seen, weaponType)
		end
	end
	table.sort(flat)
	return flat, typesByRequirement
end

local function equippedWeaponTypes()
	local env = build.calcsTab and build.calcsTab.mainEnv
	local actor = env and env.player
	local out, seen = {}, {}
	for _, weaponData in ipairs({ actor and actor.weaponData1, actor and actor.weaponData2 }) do
		if weaponData then
			addUnique(out, seen, weaponData.type ~= "None" and weaponData.type or nil)
			if weaponData.countsAsAll1H then
				for _, weaponType in ipairs({ "Claw", "Dagger", "One Hand Axe", "One Hand Mace", "One Hand Sword", "Spear" }) do
					addUnique(out, seen, weaponType)
				end
			end
			if type(weaponData.asThoughUsing) == "table" then
				for weaponType, enabled in pairs(weaponData.asThoughUsing) do
					if enabled then
						addUnique(out, seen, tostring(weaponType))
					end
				end
			end
		end
	end
	local useSecond = build.itemsTab and build.itemsTab.activeItemSet
		and build.itemsTab.activeItemSet.useSecondWeaponSet
	local weaponSlots = useSecond and { "Weapon 1 Swap", "Weapon 2 Swap" } or { "Weapon 1", "Weapon 2" }
	for _, slotName in ipairs(weaponSlots) do
		local slot = build.itemsTab and build.itemsTab.slots and build.itemsTab.slots[slotName]
		local item = slot and slot.selItemId and slot.selItemId ~= 0 and build.itemsTab.items[slot.selItemId]
		if item and item.base and item.base.type then
			addUnique(out, seen, item.base.type)
		end
	end
	table.sort(out)
	return out
end

local function activeWeaponCheck(groupIndex, activeIndex)
	local sg = build.skillsTab.socketGroupList[groupIndex or build.mainSocketGroup or 1]
	activeIndex = activeIndex or (sg and (sg.mainActiveSkill or 1))
	local active = sg and sg.displaySkillList and sg.displaySkillList[activeIndex]
	if not active then
		return nil
	end
	local flatTypes, groupedTypes = activeWeaponTypes(active)
	local disableReason = active.disableReason
	if not disableReason and active.activeEffect and active.activeEffect.statSetCalcs then
		local flags = active.activeEffect.statSetCalcs.skillFlags
		if flags and flags.disable then
			disableReason = active.disableReason or "skill disabled by PoB"
		end
	end
	return {
		skillName = skillNameAt(groupIndex, activeIndex),
		weaponTypes = flatTypes,
		weaponTypeRequirements = groupedTypes,
		equippedWeaponTypes = equippedWeaponTypes(),
		disableReason = disableReason,
		compatible = not disableReason,
	}
end

-- An Attack skill computes ~no damage without a weapon; flag it so a 0-DPS result from a fresh
-- attack build isn't mistaken for a bug (a common confusion when building from scratch).
local function attackWeaponWarning()
	local sg = build.skillsTab.socketGroupList[build.mainSocketGroup or 1]
	if not (sg and sg.displaySkillList and sg.mainActiveSkill) then
		return nil
	end
	local s = sg.displaySkillList[sg.mainActiveSkill]
	local ge = s and s.activeEffect and s.activeEffect.grantedEffect
	local attackType = (SkillType and SkillType.Attack) or 1
	if not (ge and ge.skillTypes and ge.skillTypes[attackType]) then
		return nil
	end
	local slot = build.itemsTab.slots["Weapon 1"]
	if slot and slot.selItemId and slot.selItemId ~= 0 then
		return nil
	end
	return "Main skill is an Attack but no weapon is equipped (Weapon 1) — its DPS is ~0 until "
		.. "you equip a weapon (equip_item)."
end

local function mainActiveSkill()
	local sg = build.skillsTab.socketGroupList[build.mainSocketGroup or 1]
	if sg and sg.displaySkillList and sg.mainActiveSkill then
		return sg.displaySkillList[sg.mainActiveSkill]
	end
	return nil
end

-- True if the active skill's grantedEffect carries a given SkillType (by name, resilient to enum
-- number changes; degrades to false if the enum/type is absent so we never false-positive).
local function hasType(ge, name)
	if not (ge and ge.skillTypes and type(SkillType) == "table" and SkillType[name]) then
		return false
	end
	return ge.skillTypes[SkillType[name]] and true or false
end

-- Diagnose a ~0-DPS result so an uncomputable pattern isn't mistaken for a bug (or a real build).
-- Returns the most specific applicable note, or nil. Drives off the skill's SkillTypes + the
-- actual output, not a hardcoded skill list, so it stays correct as PoB changes. Fires only when
-- DPS is ~0 (a weak-but-computable build still returns its real number).
local function damageDiagnostic()
	local w = attackWeaponWarning() -- most specific: attack with no weapon
	if w then
		return w
	end
	local act = mainActiveSkill()
	local ge = act and act.activeEffect and act.activeEffect.grantedEffect
	if not ge then
		return nil
	end
	local out = (build.calcsTab and build.calcsTab.mainOutput) or {}
	local dps = tonumber(out.TotalDPS) or tonumber(out.CombinedDPS) or 0
	if dps > 0 then
		return nil
	end
	local isDamage = hasType(ge, "Damage") or hasType(ge, "DamageOverTime")
	-- explicitly undamageable minions (e.g. the ravens) — engine can't credit player-facing DPS
	if hasType(ge, "MinionsAreUndamagable") then
		return "Main skill summons undamageable minions — the engine can't compute their "
			.. "player-facing DPS. Validate kill speed in-game."
	end
	-- buff/reservation/aura/herald that isn't itself a damage skill: ~0 DPS by design
	if
		not isDamage
		and (
			hasType(ge, "Buff")
			or hasType(ge, "HasReservation")
			or hasType(ge, "Aura")
			or hasType(ge, "Herald")
		)
	then
		return "Main skill is a buff/reservation effect, not a direct hit — the engine reports "
			.. "~0 DPS by design. Its impact comes from what it empowers; validate in-game."
	end
	-- minion skill with no computed DPS
	if hasType(ge, "Minion") then
		return "Main skill is a minion skill but the engine computes ~0 player-facing DPS "
			.. "(common for undamageable/utility minions). Validate kill speed in-game."
	end
	-- generic: a damaging skill that still computes ~0 is usually an uncomputable pattern
	if isDamage or hasType(ge, "Attack") or hasType(ge, "Spell") then
		return "Main skill computes ~0 DPS. If it's a reservation buff, an undamageable minion, "
			.. "or %-of-life / corpse detonation, that layer isn't engine-modelled — validate "
			.. "in-game rather than trusting the 0."
	end
	return nil
end

-- Skills whose effect PoB-PoE2 does not model, so their contribution is missing from the computed
-- DPS (the real in-game number is higher). Surfaced so the figure isn't read as the whole story.
local UNMODELED_SKILLS = {
	["Mana Tempest"] = "Mana Tempest is in this build but the engine does NOT model its empower "
		.. "(more damage to mana-spending spells), so the real in-game DPS is higher than shown. "
		.. "Approximate it with a custom 'more spell damage' mod if you need an estimate.",
}

local function engineLimitationNote()
	for _, sg in ipairs(build.skillsTab.socketGroupList or {}) do
		for _, g in ipairs(sg.gemList or {}) do
			local nm = g.nameSpec
			if (not nm or nm == "") and g.gemData and g.gemData.grantedEffect then
				nm = g.gemData.grantedEffect.name
			end
			if nm and UNMODELED_SKILLS[nm] then
				return UNMODELED_SKILLS[nm]
			end
		end
	end
	return nil
end

-- DPS-reading guidance. PoB labels TotalDPS as Hit DPS: average hit multiplied by use rate and any
-- quantity multiplier the engine models. FullDPS rolls up selected skill actors and DoT components.
-- The gap is diagnostic, not a guaranteed lower/upper-bound interval, because uptime, overlap and
-- simultaneous-effect assumptions remain skill- and configuration-specific.
local function dpsNoteFor(out)
	out = out or {}
	local total = tonumber(out.TotalDPS) or 0
	local full = tonumber(out.FullDPS) or 0
	local proj = tonumber(out.ProjectileCount) or 0
	if total > 0 and full > total * 1.05 then
		return "FullDPS ("
			.. math.floor(full + 0.5)
			.. ") is PoB's rollup for the skill actors/groups included in Full DPS, including modelled "
			.. "hit and damage-over-time components. TotalDPS is the selected skill's Hit DPS, not one hit. "
			.. "Neither number automatically proves real encounter uptime or projectile overlap; inspect "
			.. "the Full DPS components and verify the skill/configuration before comparison."
	elseif proj > 1 and total > 0 then
		return "This skill fires "
			.. proj
			.. " projectiles. PoB TotalDPS is Hit DPS and may already include a quantity multiplier known "
			.. "to the engine. Whether additional projectiles overlap one target, improve only coverage, "
			.. "or feed secondary effects is per-skill; verify instead of multiplying projectile count."
	end
	return nil
end

local selectMainSocketGroup

local function socketGroupActiveGemCount(sg, activeIndex, active)
	if not sg then
		return 1
	end
	if sg.groupCount then
		local groupCount = asNumber(sg.groupCount)
		if groupCount > 0 then
			return groupCount
		end
	end
	local granted = active and active.activeEffect and active.activeEffect.grantedEffect
	if granted and sg.gemList then
		for _, gemData in ipairs(sg.gemList) do
			local gd = gemData.gemData
			if gd then
				if gd.vaalGem and gd.grantedEffectList then
					if granted == gd.grantedEffectList[1] or granted == gd.grantedEffectList[2] then
						return asNumber(gemData.count) > 0 and asNumber(gemData.count) or 1
					end
				elseif (gd.grantedEffect and granted == gd.grantedEffect and not gd.grantedEffect.support)
					or (gd.additionalGrantedEffects and isValueInArray(gd.additionalGrantedEffects, granted)) then
					return asNumber(gemData.count) > 0 and asNumber(gemData.count) or 1
				end
			end
		end
	end
	local seenActive = 0
	for _, gemData in ipairs(sg.gemList or {}) do
		local gd = gemData.gemData
		local isSupport = gd and gd.grantedEffect and gd.grantedEffect.support
		if not isSupport then
			seenActive = seenActive + 1
			if seenActive == (activeIndex or 1) then
				local count = asNumber(gemData.count)
				return count > 0 and count or 1
			end
		end
	end
	return 1
end

local function judgeSkillGroupOrigin(sg)
	if not sg then
		return "unknown"
	end
	if sg.source == "Explode" then
		return "synthetic_on_kill"
	end
	if sg.source == "Thorns" then
		return "synthetic_reactive"
	end
	if sg.source and sg.source ~= "" then
		return "granted_or_generated"
	end
	return "socketed"
end

local function judgeSocketLegalityApplicable(sg)
	local origin = judgeSkillGroupOrigin(sg)
	return origin ~= "synthetic_on_kill" and origin ~= "synthetic_reactive"
end

local function activeSkillSummary(groupIndex, activeIndex)
	local sg = build.skillsTab.socketGroupList[groupIndex or build.mainSocketGroup or 1]
	activeIndex = activeIndex or (sg and (sg.mainActiveSkill or 1))
	local active = sg and sg.displaySkillList and sg.displaySkillList[activeIndex]
	local ge = active and active.activeEffect and active.activeEffect.grantedEffect
	local activeSkillCount = 1
	local activeSkillCountAvailable = false
	if active and calcs and calcs.getActiveSkillCount then
		local ok, count = pcall(calcs.getActiveSkillCount, active)
		if ok then
			activeSkillCount = asNumber(count)
			if activeSkillCount <= 0 then
				activeSkillCount = 1
			end
			activeSkillCountAvailable = true
		end
	end
	local fallbackCount = socketGroupActiveGemCount(sg, activeIndex, active)
	if fallbackCount > activeSkillCount then
		activeSkillCount = fallbackCount
		activeSkillCountAvailable = true
	end
	local tags = {}
	local utilityTags = {}
	if ge and ge.skillTypes and type(SkillType) == "table" then
		for _, name in ipairs({
			"Attack",
			"Spell",
			"Damage",
			"DamageOverTime",
			"Minion",
			"Buff",
			"Aura",
			"Herald",
			"HasReservation",
			"Projectile",
			"Hex",
			"Mark",
			"Warcry",
			"Travel",
			"Banner",
		}) do
			if SkillType[name] and ge.skillTypes[SkillType[name]] then
				tags[#tags + 1] = name
			end
		end
	end
	local function hasSkillTag(name)
		return ge and ge.skillTypes and type(SkillType) == "table" and SkillType[name] and ge.skillTypes[SkillType[name]]
	end
	if hasSkillTag("Buff") then utilityTags[#utilityTags + 1] = "Buff" end
	if hasSkillTag("Aura") then utilityTags[#utilityTags + 1] = "Aura" end
	if hasSkillTag("Herald") then utilityTags[#utilityTags + 1] = "Herald" end
	if hasSkillTag("HasReservation") then utilityTags[#utilityTags + 1] = "HasReservation" end
	if hasSkillTag("Hex") then utilityTags[#utilityTags + 1] = "Hex" end
	if hasSkillTag("Mark") then utilityTags[#utilityTags + 1] = "Mark" end
	if hasSkillTag("Warcry") then utilityTags[#utilityTags + 1] = "Warcry" end
	if hasSkillTag("Travel") then utilityTags[#utilityTags + 1] = "Travel" end
	if hasSkillTag("Banner") then utilityTags[#utilityTags + 1] = "Banner" end
	local hasDirectDamageTag = hasSkillTag("Damage") or hasSkillTag("DamageOverTime") or hasSkillTag("Attack") or hasSkillTag("Minion")
	local utilityOnly = (#utilityTags > 0) and not hasDirectDamageTag
	local groupOrigin = judgeSkillGroupOrigin(sg)
	local scenarioLimitations = {}
	if groupOrigin == "synthetic_on_kill" then
		scenarioLimitations[#scenarioLimitations + 1] = "requires_kill"
	elseif groupOrigin == "synthetic_reactive" then
		scenarioLimitations[#scenarioLimitations + 1] = "requires_enemy_hit"
	end
	return {
		groupIndex = groupIndex or build.mainSocketGroup or 1,
		activeIndex = activeIndex,
		skillName = skillNameAt(groupIndex, activeIndex),
		tags = tags,
		utilityTags = utilityTags,
		isMinion = ge and hasType(ge, "Minion") or false,
		isDamageTagged = ge and (hasType(ge, "Damage") or hasType(ge, "DamageOverTime") or hasType(ge, "Attack") or hasType(ge, "Minion")) or false,
		utilityOnly = utilityOnly,
		activeSkillCount = activeSkillCount,
		activeSkillCountAvailable = activeSkillCountAvailable,
		weaponCheck = activeWeaponCheck(groupIndex, activeIndex),
		groupOrigin = groupOrigin,
		groupSource = sg and sg.source or nil,
		socketLegalityApplicable = judgeSocketLegalityApplicable(sg),
		scenarioLimitations = scenarioLimitations,
	}
end

local function isBetterJudgeCandidate(candidate, best)
	if not best then
		return true
	end
	if candidate.dps ~= best.dps then
		return candidate.dps > best.dps
	end
	local candidateUtility = candidate.utilityOnly and 1 or 0
	local bestUtility = best.utilityOnly and 1 or 0
	if candidateUtility ~= bestUtility then
		return candidateUtility < bestUtility
	end
	local candidateDirect = candidate.hasDirectDamageTag and 1 or 0
	local bestDirect = best.hasDirectDamageTag and 1 or 0
	if candidateDirect ~= bestDirect then
		return candidateDirect > bestDirect
	end
	return (candidate.activeIndex or 0) > (best.activeIndex or 0)
end

local function selectedDamageMetric(out, allowFullDPS, allowMinionOutput)
	out = out or {}
	local candidates = {
		{ key = "CombinedDPS", value = asNumber(out.CombinedDPS) },
		{ key = "WithPoisonDPS", value = asNumber(out.WithPoisonDPS) },
		{ key = "WithIgniteDPS", value = asNumber(out.WithIgniteDPS) },
		{ key = "WithBleedDPS", value = asNumber(out.WithBleedDPS) },
		{ key = "WithImpaleDPS", value = asNumber(out.WithImpaleDPS) },
		{ key = "WithDotDPS", value = asNumber(out.WithDotDPS) },
		{ key = "TotalDPS", value = asNumber(out.TotalDPS) },
		{ key = "TotalDot", value = asNumber(out.TotalDot) },
		{ key = "TotalDotDPS", value = asNumber(out.TotalDotDPS) },
	}
	if allowMinionOutput then
		candidates[#candidates + 1] = { key = "MinionCombinedDPS", value = asNumber(outputValue(out, "MinionCombinedDPS")) }
		candidates[#candidates + 1] = { key = "MinionTotalDPS", value = asNumber(outputValue(out, "MinionTotalDPS")) }
	end
	local best = { key = "TotalDPS", value = 0 }
	for _, candidate in ipairs(candidates) do
		if candidate.value and candidate.value > best.value then
			best = candidate
		end
	end
	local directDPS = best.value or 0
	local fullDPS = asNumber(out.FullDPS)
	if allowFullDPS and fullDPS > 0 then
		-- FullDPS is a limited-evidence rollup. Prefer a direct PoB metric when the two are equal
		-- within floating-point noise; use FullDPS only when it adds a material component or no
		-- direct metric exists.
		local tolerance = math.max(0.000001, math.abs(directDPS) * 0.000001)
		if directDPS <= 0 or fullDPS > directDPS + tolerance then
			best = { key = "FullDPS", value = fullDPS }
		end
	end
	best.directDPS = directDPS
	best.fullDPS = fullDPS
	return best
end

local function computeJudgeSelectedSkill()
	local list = build.skillsTab.socketGroupList or {}
	local originalGroup = build.mainSocketGroup or 1
	local originalActive = {}
	local originalFullDPS = {}
	for i, sg in ipairs(list) do
		originalActive[i] = sg.mainActiveSkill
		originalFullDPS[i] = sg.includeInFullDPS
	end
	local best = nil
	local supplemental = {}
	for i, sg in ipairs(list) do
		if sg and sg.enabled ~= false and sg.displaySkillList and #sg.displaySkillList > 0 then
			for activeIndex = 1, #sg.displaySkillList do
				for j, other in ipairs(list) do
					other.includeInFullDPS = (j == i)
				end
				selectMainSocketGroup(i, activeIndex)
				local out = (build.calcsTab and build.calcsTab.mainOutput) or {}
				local summary = activeSkillSummary(i, activeIndex)
				local metric = selectedDamageMetric(out, true, summary.isMinion)
				local rawValue = metric.value or 0
				local effectiveValue = rawValue
				local activeMinionLimit = asNumber(outputValue(out, "ActiveMinionLimit"))
				local isMinionMetric = metric.key == "MinionCombinedDPS" or metric.key == "MinionTotalDPS"
				local isMinionCandidate = summary.isMinion or isMinionMetric
				local caveats = {}
				if isMinionMetric and metric.key ~= "FullDPS" then
					if summary.activeSkillCountAvailable and summary.activeSkillCount > 0 then
						effectiveValue = rawValue * summary.activeSkillCount
						caveats[#caveats + 1] = "minion_count_multiplier_caveat"
					elseif activeMinionLimit > 0 then
						effectiveValue = rawValue * activeMinionLimit
						caveats[#caveats + 1] = "minion_count_multiplier_caveat"
					end
				end
				local value = effectiveValue
				if value > 0 or summary.isDamageTagged then
					local candidate = {
						groupIndex = i,
						activeIndex = summary.activeIndex,
						skillName = summary.skillName,
						dps = value,
						rawDps = rawValue,
						effectiveDps = effectiveValue,
						directDps = metric.directDPS,
						fullDps = metric.fullDPS,
						sourceMetric = metric.key,
						projectileCount = asNumber(out.ProjectileCount),
						activeSkillCount = summary.activeSkillCount,
						tags = summary.tags,
						utilityTags = summary.utilityTags,
						utilityOnly = summary.utilityOnly,
						hasDirectDamageTag = summary.isDamageTagged,
						weaponCheck = summary.weaponCheck,
						caveats = caveats,
						groupOrigin = summary.groupOrigin,
						groupSource = summary.groupSource,
						socketLegalityApplicable = summary.socketLegalityApplicable,
						scenarioLimitations = summary.scenarioLimitations,
					}
					if isMinionCandidate then
						candidate.isMinion = true
						candidate.activeMinionLimit = activeMinionLimit
						candidate.caveats[#candidate.caveats + 1] = "minion_dps_unverified_caveat"
					end
					if asNumber(out.ProjectileCount) > 1 and metric.key ~= "FullDPS" then
						candidate.caveats[#candidate.caveats + 1] = "projectile_overlap_unverified_caveat"
					end
					if summary.groupOrigin == "synthetic_on_kill" or summary.groupOrigin == "synthetic_reactive" then
						supplemental[#supplemental + 1] = candidate
					elseif isBetterJudgeCandidate(candidate, best) then
						best = candidate
					end
				end
			end
		end
	end
	selectMainSocketGroup(originalGroup, originalActive[originalGroup])
	for i, sg in ipairs(list) do
		if sg and originalActive[i] then
			sg.mainActiveSkill = originalActive[i]
			sg.mainActiveSkillCalcs = originalActive[i]
		end
		if sg then
			sg.includeInFullDPS = originalFullDPS[i]
		end
	end
	runCallback("OnFrame")
	if best and best.groupIndex ~= originalGroup then
		best.caveats[#best.caveats + 1] = "auto_selected_damage_skill_caveat"
	end
	return best, supplemental
end

local function computeJudgeSkillCandidates()
	local list = build.skillsTab.socketGroupList or {}
	local originalGroup = build.mainSocketGroup or 1
	local originalActive = {}
	local originalFullDPS = {}
	local outCandidates = {}
	for i, sg in ipairs(list) do
		originalActive[i] = sg.mainActiveSkill
		originalFullDPS[i] = sg.includeInFullDPS
	end
	for i, sg in ipairs(list) do
		if sg and sg.enabled ~= false and sg.displaySkillList and #sg.displaySkillList > 0 then
			for activeIndex = 1, #sg.displaySkillList do
				for j, other in ipairs(list) do
					other.includeInFullDPS = (j == i)
				end
				selectMainSocketGroup(i, activeIndex)
				local calcsOut = (build.calcsTab and build.calcsTab.mainOutput) or {}
				local summary = activeSkillSummary(i, activeIndex)
				local metric = selectedDamageMetric(calcsOut, true, summary.isMinion)
				outCandidates[#outCandidates + 1] = {
					groupIndex = i,
					activeIndex = activeIndex,
					skillName = summary.skillName,
					tags = summary.tags,
					isDamageTagged = summary.isDamageTagged,
					isMinion = summary.isMinion,
					sourceMetric = metric.key,
					rawMetricValue = metric.value,
					totalDPS = asNumber(calcsOut.TotalDPS),
					fullDPS = asNumber(calcsOut.FullDPS),
					combinedDPS = asNumber(calcsOut.CombinedDPS),
					projectileCount = asNumber(calcsOut.ProjectileCount),
					weaponCheck = summary.weaponCheck,
				}
			end
		end
	end
	selectMainSocketGroup(originalGroup, originalActive[originalGroup])
	for i, sg in ipairs(list) do
		if sg and originalActive[i] then
			sg.mainActiveSkill = originalActive[i]
			sg.mainActiveSkillCalcs = originalActive[i]
		end
		if sg then
			sg.includeInFullDPS = originalFullDPS[i]
		end
	end
	runCallback("OnFrame")
	return outCandidates
end

-- Standard {mainSkill, stats} response, with a warning attached when one applies.
local function statResult(keys)
	local r = { mainSkill = mainSkillName(), stats = collectStats(keys) }
	local w = damageDiagnostic()
	if w then
		r.warning = w
	end
	local el = engineLimitationNote()
	if el then
		r.engineNote = el
	end
	local note = dpsNoteFor((build.calcsTab and build.calcsTab.mainOutput) or {})
	if note then
		r.dpsNote = note
	end
	return r
end

-- PoB's paste parser REQUIRES a trailing instance count on every gem line ("Name L/Q  count"),
-- so a support written "<Support> 20/20" (no count) is silently dropped. Tolerate that by
-- appending "  1" to any gem line that has level/quality but no count.
local function normalizeSkillText(text)
	local lines = {}
	for line in tostring(text or ""):gmatch("([^\r\n]+)") do
		if line:match("^%s*[%a':][%a':' ]* %d+/%d+%s*%u*%s*$") then
			line = line:gsub("%s*$", "") .. "  1"
		end
		lines[#lines + 1] = line
	end
	return table.concat(lines, "\n")
end

function selectMainSocketGroup(index, activeIndex)
	index = index or 1
	build.mainSocketGroup = index
	local sg = build.skillsTab.socketGroupList[index]
	if sg then
		local active = activeIndex or 1
		sg.mainActiveSkill = active
		sg.mainActiveSkillCalcs = active
	end
	if build.calcsTab and build.calcsTab.input then
		build.calcsTab.input.skill_number = index
	end
	build.buildFlag = true
	build.modFlag = true
	runCallback("OnFrame")
end

-- ---------------------------------------------------------------------------
-- methods
-- ---------------------------------------------------------------------------
local methods = {}

function methods.ping()
	return { pong = true, jit = jit and jit.version }
end

function methods.new_build()
	newBuild(); runCallback("OnFrame")
	return { stats = collectStats() }
end

-- Set the character class and (optionally) ascendancy, re-rooting the passive tree at that
-- class's start so search/alloc/optimize work for the right class.
function methods.set_class(p)
	assert(p and p.class, "set_class requires params.class")
	local spec = build.spec
	local tree = spec.tree

	local classId = tree.classNameMap[p.class]
	if not classId then
		local want = tostring(p.class):lower()
		for name, id in pairs(tree.classNameMap) do
			if name:lower() == want then
				classId = id
				break
			end
		end
	end
	if not classId then
		local valid = {}
		for name in pairs(tree.classNameMap) do
			valid[#valid + 1] = name
		end
		table.sort(valid)
		return {
			ok = false,
			error = "unknown class '" .. tostring(p.class) .. "'. Valid classes: "
				.. table.concat(valid, ", "),
		}
	end
	spec:SelectClass(classId)

	if p.ascendancy and p.ascendancy ~= "" then
		local want = tostring(p.ascendancy):lower()
		local found
		for aid, asc in pairs(tree.classes[classId].classes) do
			if asc.name and asc.name:lower() == want then
				spec:SelectAscendClass(aid)
				found = asc.name
				break
			end
		end
		if not found then
			local valid = {}
			for _, asc in pairs(tree.classes[classId].classes) do
				if asc.name and asc.name ~= "" and asc.name ~= "None" then
					valid[#valid + 1] = asc.name
				end
			end
			table.sort(valid)
			return {
				ok = false,
				error = "unknown ascendancy '"
					.. tostring(p.ascendancy)
					.. "' for class "
					.. tostring(p.class)
					.. ". Valid ascendancies: "
					.. table.concat(valid, ", "),
			}
		end
	end

	build.buildFlag = true
	build.modFlag = true
	runCallback("OnFrame")
	return {
		ok = true,
		class = spec.curClassName,
		ascendancy = spec.curAscendClassName,
		stats = collectStats(p.keys),
	}
end

-- Set the character level (1-100). Disables auto-leveling so the value sticks.
function methods.set_level(p)
	local lvl = tonumber(p and p.level)
	if not lvl then
		return { ok = false, error = "set_level requires numeric params.level" }
	end
	lvl = math.max(1, math.min(100, math.floor(lvl)))
	build.characterLevelAutoMode = false
	build.characterLevel = lvl
	if build.controls and build.controls.characterLevel then
		build.controls.characterLevel:SetText(tostring(lvl))
	end
	build.buildFlag = true
	build.modFlag = true
	runCallback("OnFrame")
	return { ok = true, level = build.characterLevel, stats = collectStats(p.keys) }
end

function methods.load_build_xml(p)
	assert(p and p.xml, "load_build_xml requires params.xml")
	loadBuildFromXML(p.xml, p.name or "imported")
	runCallback("OnFrame")
	return {
		mainSkill = mainSkillName(),
		treeVersion = build.spec and build.spec.treeVersion,
		latestTreeVersion = latestTreeVersion,
		stats = collectStats(p.keys),
	}
end

-- Set the build's MAIN skill from PoB's paste format ("<Gem> 20/0  1", one gem per line). This
-- REPLACES the current main socket group (auras/buffs added via add_skill_group are separate groups
-- and are preserved) so repeated calls don't pile up stale groups. On a parse failure it rolls the
-- build back and reports, rather than silently leaving a broken/"phantom" main skill.
function methods.paste_skill(p)
	assert(p and p.text, "paste_skill requires params.text")
	local list = build.skillsTab.socketGroupList
	local snapshot = build:SaveDB("code")
	local prevMain = build.mainSocketGroup
	local before = #list
	build.skillsTab:PasteSocketGroup(normalizeSkillText(p.text))
	if #list <= before then
		-- Nothing parsed: don't repoint main at a stale group (the old corruption). Restore + report.
		loadBuildFromXML(snapshot)
		runCallback("OnFrame")
		return {
			ok = false,
			error = "no gem could be parsed from the skill text. Use PoB paste format with ONE GEM "
				.. "PER LINE — 'Name level/quality count' (e.g. '<gem name> 20/20 1') — the main skill "
				.. "first and each support on its own line. ' / ', '|' or ',' between gems also work.",
			mainSkill = mainSkillName(),
		}
	end
	-- The new main skill is the FIRST group the paste appended; make it main and REMOVE the previous
	-- main group so set_skill replaces rather than accumulates (aura/buff groups are untouched).
	local newIndex = before + 1
	if prevMain and prevMain >= 1 and prevMain <= before and prevMain ~= newIndex then
		table.remove(list, prevMain)
		if newIndex > prevMain then
			newIndex = newIndex - 1
		end
	end
	if build.skillsTab.controls and build.skillsTab.controls.groupList then
		build.skillsTab.controls.groupList.selIndex = newIndex
		build.skillsTab.controls.groupList.selValue = list[newIndex]
	end
	-- Compute FullDPS for the main skill (PoB only rolls it up for groups flagged "include in Full
	-- DPS"; off by default). This exposes PoB's selected-actor/component rollup alongside Hit DPS.
	if list[newIndex] then
		list[newIndex].includeInFullDPS = true
	end
	selectMainSocketGroup(newIndex)
	-- A syntactically valid but unrecognized gem name parses into a group with no real skill (it
	-- would read ~0 DPS). Don't leave the build in that state — restore + report.
	if not mainSkillName() then
		loadBuildFromXML(snapshot)
		runCallback("OnFrame")
		return {
			ok = false,
			error = "the main gem name wasn't recognized as a skill — check spelling with "
				.. "find_skills. Build left unchanged.",
			mainSkill = mainSkillName(),
		}
	end
	return statResult(p.keys)
end

-- Add an ENABLED secondary socket group (an aura/herald/reservation buff, or a second
-- skill) WITHOUT changing the main skill, so its buff/reservation applies to the active build.
-- This is how caster damage layers (auras, reservation/mana-scaling buffs) get modelled.
function methods.add_skill_group(p)
	assert(p and p.text, "add_skill_group requires params.text")
	local list = build.skillsTab.socketGroupList
	local prevMain = build.mainSocketGroup or 1
	local before = #list
	build.skillsTab:PasteSocketGroup(normalizeSkillText(p.text))
	-- Optionally include a second DAMAGE skill in FullDPS (clear+boss, triggers). Off by default so
	-- auras/heralds/buffs don't inflate the combined number.
	if p.includeInFullDPS then
		for i = before + 1, #list do
			list[i].includeInFullDPS = true
		end
	end
	runCallback("OnFrame")
	-- keep the existing main skill; the new group stays enabled and applies its effect
	selectMainSocketGroup(prevMain)
	return statResult(p.keys)
end

function methods.set_main_socket_group(p)
	selectMainSocketGroup(p and p.index or 1, p and p.activeIndex or 1)
	return statResult(p and p.keys)
end

function methods.debug_judge_skill_candidates()
	return { candidates = computeJudgeSkillCandidates() }
end

function methods.get_stats(p)
	return statResult(p and p.keys)
end

-- Serialize the current build to PoB XML (same payload PoB compresses into a share code).
function methods.get_xml()
	return { xml = build:SaveDB("code") }
end

-- Standard PoB enemy elemental resistance per boss tier (matches PoB's GUI placeholders, which
-- headless otherwise ignores — leaving bosses at 0% resistance, which overstates non-penetration
-- DPS and hides the value of penetration/exposure).
local BOSS_ELE_RES = { Boss = 30, Pinnacle = 50, Uber = 50 }

-- Set combat/config options (configTab.input keys) and/or raw custom mods, then recompute.
function methods.set_config(p)
	p = p or {}
	local opts = (type(p.options) == "table") and p.options or {}
	for k, v in pairs(opts) do
		build.configTab.input[k] = v
	end
	-- When the caller sets the boss tier, apply that tier's standard enemy resistances so boss DPS
	-- is realistic (PoB only sets these as GUI placeholders). Explicit enemy*Resist in the same
	-- call wins; "None" clears them back to 0.
	local appliedRes
	if opts.enemyIsBoss ~= nil then
		local ele = BOSS_ELE_RES[opts.enemyIsBoss] or 0
		local ci = build.configTab.input
		if opts.enemyLightningResist == nil then
			ci.enemyLightningResist = ele
		end
		if opts.enemyColdResist == nil then
			ci.enemyColdResist = ele
		end
		if opts.enemyFireResist == nil then
			ci.enemyFireResist = ele
		end
		if opts.enemyChaosResist == nil then
			ci.enemyChaosResist = 0
		end
		appliedRes = ele
	end
	if type(p.customMods) == "string" then
		build.configTab.input.customMods = p.customMods
	end
	build.configTab:BuildModList()
	runCallback("OnFrame")
	local r = { stats = collectStats(p.keys) }
	if appliedRes ~= nil then
		r.enemyResist = {
			fire = build.configTab.input.enemyFireResist,
			cold = build.configTab.input.enemyColdResist,
			lightning = build.configTab.input.enemyLightningResist,
			chaos = build.configTab.input.enemyChaosResist,
			note = "Enemy resistances set to the "
				.. tostring(opts.enemyIsBoss)
				.. " tier (penetration/exposure now matter). Override via enemy*Resist.",
		}
	end
	return r
end

-- Parse raw PoB item text and place it in a slot (REPLACING what's there). Returns ok, slotOrErr.
-- PoB's parser throws (e.g. "attempt to index local 'item'") on an unrecognized base/malformed
-- block; we pcall it so callers get a message, not a raw traceback.
local function equipItemRaw(raw, slot)
	local items = build.itemsTab.items
	local before = {}
	for id in pairs(items) do
		before[id] = true
	end
	local ok, err = pcall(function()
		build.itemsTab:CreateDisplayItemFromRaw(raw)
		build.itemsTab:AddDisplayItem(true) -- add without auto-equip; we place it explicitly
	end)
	if not ok then
		return false, "parse error: " .. tostring(err)
	end
	local newItem
	for id, it in pairs(items) do
		if not before[id] then
			newItem = it
			break
		end
	end
	if not newItem then
		return false, "item not created (unrecognized base type?)"
	end
	local sl = slot or newItem:GetPrimarySlot()
	local sc = build.itemsTab.slots[sl]
	if not sc then
		return false, "unknown slot: " .. tostring(sl)
	end
	sc:SetSelItemId(newItem.id) -- replaces any existing item in the slot
	build.buildFlag = true
	build.modFlag = true
	return true, sl
end

-- Equip an item from raw PoB item text, REPLACING whatever is in the target slot.
-- p.slot optionally forces a slot (e.g. "Ring 2", "Weapon 2"); otherwise the item's primary slot.
function methods.add_item(p)
	assert(p and p.raw, "add_item requires params.raw")
	local ok, slotOrErr = equipItemRaw(p.raw, p.slot)
	if not ok then
		return {
			ok = false,
			error = "could not equip — check the BASE TYPE is a real PoE2 base on its own line "
				.. "directly under the name, and the block is well-formed (Rarity / name / base, "
				.. "then mods). For attack weapons an unbound base has no attack rate and breaks "
				.. "DPS. ("
				.. slotOrErr
				.. ")",
		}
	end
	runCallback("OnFrame")
	return { ok = true, slot = slotOrErr, stats = collectStats(p.keys) }
end

-- Surface PoB's OWN crafting data (runes / soul cores, corrupted implicits, essence-forced mods)
-- applicable to the item in `slot`, resolved to ready-to-use item-text mod lines. The Python craft
-- layer assembles candidate items from these and values them on the engine — PoB owns the data and
-- the math, so this never invents a number. (Runes apply automatically from `Sockets:`/`Rune:` lines;
-- a corrupted implicit is an implicit line on a `Corrupted` item; an essence forces one explicit mod.)
function methods.crafting_options(p)
	assert(p and p.slot, "crafting_options requires params.slot")
	local sc = build.itemsTab.slots[p.slot]
	local item = sc and sc.selItemId and sc.selItemId ~= 0 and build.itemsTab.items[sc.selItemId]
	if not item or not item.base then
		return { ok = false, error = "no item in slot '" .. tostring(p.slot) .. "' — equip a base first." }
	end
	local base = item.base
	local tags = base.tags or {}
	local itemType = base.type and base.type:lower() or ""
	local subType = base.subType and base.subType:lower()
	local baseType = (base.weapon and "weapon") or (base.armour and "armour")
		or ((tags.wand or tags.staff or tags.sceptre) and "caster") or nil
	local specificType = (subType == "warstaff" and "warstaff")
		or (itemType == "shield" and subType == "evasion" and "buckler") or itemType

	-- runes / soul cores: those whose data has an entry for this item's rune-type keys. Match PoB's
	-- UpdateRunes (baseType + specificType only) and DEDUPE — specificType defaults to itemType, so a
	-- naive {baseType, specificType, itemType} would double-count a rune's mods on most items.
	local runes = {}
	for name, rdata in pairs(data.itemMods.Runes or {}) do
		local mods, seen = {}, {}
		for _, key in ipairs({ baseType, specificType }) do
			if key and not seen[key] and rdata[key] then
				seen[key] = true
				for _, line in ipairs(rdata[key]) do
					mods[#mods + 1] = line
				end
			end
		end
		if #mods > 0 then
			runes[#runes + 1] = { name = name, mods = mods }
		end
	end

	-- corrupted implicits: those whose weightKey (weight > 0) intersects this base's tags
	local corruptions = {}
	for _, m in pairs(data.itemMods.Corruption or {}) do
		local applies = false
		if m.weightKey then
			for i, k in ipairs(m.weightKey) do
				if (m.weightVal[i] or 0) > 0 and tags[k] then
					applies = true
					break
				end
			end
		end
		if applies and m[1] then
			corruptions[#corruptions + 1] = { line = m[1], group = m.group }
		end
	end

	-- essences: those that force a mod on this item class, resolved to the mod's stat line. `special`
	-- marks the beyond-the-normal-pool mods (Perfect essences — % Life, "damage as extra", …).
	local essences = {}
	for _, e in pairs(data.essences or {}) do
		local modId = e.mods and e.mods[base.type]
		local m = modId and data.itemMods.Item[modId]
		if m and m[1] then
			essences[#essences + 1] = {
				name = e.name,
				tier = e.tierLevel,
				stat = m[1],
				modType = m.type,
				group = m.group,
				special = modId:find("^Essence") ~= nil,
			}
		end
	end

	return {
		ok = true,
		slot = p.slot,
		base = base.name or base.type,
		runeType = baseType,
		itemType = itemType,
		runes = runes,
		corruptions = corruptions,
		essences = essences,
	}
end

-- List the passive tree's jewel sockets so a jewel can be placed. A jewel only contributes when its
-- socket node is ALLOCATED; `filled` shows whether one is already socketed there.
function methods.list_jewel_sockets()
	local spec = build.spec
	local out = {}
	for id, sc in pairs(build.itemsTab.sockets or {}) do
		local node = spec.nodes[id]
		out[#out + 1] = {
			socket = id,
			allocated = (node and node.alloc) and true or false,
			filled = (sc.selItemId and sc.selItemId ~= 0) and true or false,
			name = (node and (node.dn or node.name)) or "Jewel Socket",
		}
	end
	table.sort(out, function(a, b)
		if a.allocated ~= b.allocated then
			return a.allocated -- allocated sockets first
		end
		return a.socket < b.socket
	end)
	return { sockets = out }
end

-- equipItemRaw only places a jewel in its socket slot; it does NOT register it in the passive
-- spec's socket->jewel map (which is otherwise built only on build load), and nothing rebuilds the
-- tree paths afterwards. So a socketed jewel's TREE-modifying effects (alternate class starts,
-- radius/cluster/timeless grants) silently never apply, and optimize_passives/alloc_passive don't
-- see the pathing it opens. Sync the map from the slot for `socket`, then rebuild paths.
local function syncJewelSocket(socket)
	local sc = build.itemsTab.slots["Jewel " .. tostring(socket)]
	local jid = sc and sc.selItemId
	if jid and jid ~= 0 and build.itemsTab.items[jid] then
		build.spec.jewels[socket] = jid
	else
		build.spec.jewels[socket] = nil
	end
	build.spec:BuildAllDependsAndPaths()
end

-- Place a jewel (raw PoB item text) into a tree jewel socket. p.socket is a socket id from
-- list_jewel_sockets; if omitted, the first ALLOCATED empty socket is used. A jewel in an
-- unallocated socket does nothing, so we warn instead of silently wasting it.
function methods.equip_jewel(p)
	assert(p and p.raw, "equip_jewel requires params.raw")
	local spec = build.spec
	local socket = p.socket
	if socket == nil then
		local ids = {}
		for id in pairs(build.itemsTab.sockets or {}) do
			ids[#ids + 1] = id
		end
		table.sort(ids)
		for _, id in ipairs(ids) do
			local sc = build.itemsTab.sockets[id]
			local node = spec.nodes[id]
			if node and node.alloc and not (sc.selItemId and sc.selItemId ~= 0) then
				socket = id
				break
			end
		end
		if socket == nil then
			return {
				ok = false,
				error = "no allocated empty jewel socket — allocate a Socket node (alloc_passive) "
					.. "or pass socket= from list_jewel_sockets.",
			}
		end
	end
	if not build.itemsTab.sockets[socket] then
		return {
			ok = false,
			error = "unknown jewel socket '"
				.. tostring(socket)
				.. "' — see list_jewel_sockets for valid socket ids.",
		}
	end
	local ok, slotOrErr = equipItemRaw(p.raw, "Jewel " .. tostring(socket))
	if not ok then
		return {
			ok = false,
			error = "could not place jewel ("
				.. slotOrErr
				.. "). Check the base is a real jewel base (e.g. 'Sapphire') on its own line "
				.. "under the name.",
		}
	end
	syncJewelSocket(socket) -- register the jewel in the tree + rebuild paths (see helper above)
	runCallback("OnFrame")
	local node = spec.nodes[socket]
	local r = { ok = true, socket = socket, stats = collectStats(p.keys) }
	if not (node and node.alloc) then
		r.warning = "socket "
			.. tostring(socket)
			.. " is NOT allocated — this jewel contributes nothing until you allocate it "
			.. "(alloc_passive)."
	end
	return r
end

-- Batch-evaluate many candidate items in one slot, returning each one's requested stats. Used by
-- the gear optimizer to score crafted candidates in a single round-trip. Restores the build after.
function methods.eval_items(p)
	assert(p and p.slot and type(p.items) == "table", "eval_items requires slot + items[]")
	local keys = p.keys or { "TotalDPS" }
	local snapshot = build:SaveDB("code")
	local out = {}
	for i, raw in ipairs(p.items) do
		local ok = equipItemRaw(raw, p.slot)
		if ok then
			runCallback("OnFrame")
			out[i] = collectStats(keys)
		else
			out[i] = false -- candidate failed to parse/equip
		end
	end
	loadBuildFromXML(snapshot)
	runCallback("OnFrame")
	return { results = out }
end

-- Clear an equipment slot (e.g. "Ring 2", "Body Armour").
function methods.unequip_item(p)
	local slot = p and p.slot
	local sc = slot and build.itemsTab.slots[slot]
	if not sc then
		return { ok = false, error = "unknown slot: " .. tostring(slot) }
	end
	sc:SetSelItemId(0)
	build.buildFlag = true
	-- If this was a jewel socket, drop it from the tree map + rebuild paths so its effects go away.
	local jewelSocket = tostring(slot):match("^Jewel (%d+)$")
	if jewelSocket then
		syncJewelSocket(tonumber(jewelSocket))
	end
	runCallback("OnFrame")
	return { ok = true, slot = slot, stats = collectStats(p.keys) }
end

-- Full read-back of the active build (so callers can see what they've assembled).
function methods.get_build()
	local spec = build.spec
	local notables, keystones, asc = {}, {}, {}
	for _, node in pairs(spec.allocNodes) do
		if node.ascendancyName then
			if node.type == "Notable" then
				table.insert(asc, node.name)
			end
		elseif node.type == "Keystone" then
			table.insert(keystones, node.name)
		elseif node.type == "Notable" then
			table.insert(notables, node.name)
		end
	end
	table.sort(notables)
	table.sort(keystones)
	table.sort(asc)

	local gems = gemSummaryForSocketGroup(build.mainSocketGroup or 1)

	local gear = {}
	for slotName, slot in pairs(build.itemsTab.slots) do
		local id = slot.selItemId
		if id and id ~= 0 and build.itemsTab.items[id] then
			local it = build.itemsTab.items[id]
			gear[slotName] = {
				name = it.title,
				base = it.baseName,
				rarity = it.rarity,
				itemLevel = it.itemLevel,
				levelRequirement = it.requirements and it.requirements.level or nil,
				runeSockets = #(it.sockets or {}),
				runes = it.runes or {},
				charmSlots = it.charmLimit,
				isScaffold = type(it.title) == "string" and it.title:match("^Scaffold ") ~= nil,
			}
		end
	end

	-- CountAllocNodes includes nodes allocated to weapon-set variants. PoB's own budget display
	-- subtracts the shared weapon-set overlap from normal passive usage, then validates each weapon
	-- set against its separate pool.
	local used, ascUsed, secondaryAscUsed, socketsUsed, weaponSet1Used, weaponSet2Used = spec:CountAllocNodes()
	local avail = availablePoints()
	local mainOutput = ((build.calcsTab or {}).mainOutput or {})
	local weaponSetAvail = (build.maxWeaponSets or 0)
		+ asNumber(mainOutput.PassivePointsToWeaponSetPoints)
	local normalPassiveUsed = used - math.min(weaponSet1Used or 0, weaponSet2Used or 0)
	local unspent = math.max(0, avail - normalPassiveUsed)
	local judgeSelectedSkill, judgeSupplementalSkills = computeJudgeSelectedSkill()
	local r = {
		class = spec.curClassName,
		ascendancy = spec.curAscendClassName,
		level = build.characterLevel,
		treeVersion = spec.treeVersion,
		latestTreeVersion = latestTreeVersion,
		mainSkill = mainSkillName(),
		mainSkillWeaponCheck = activeWeaponCheck(build.mainSocketGroup or 1),
		judgeSelectedSkill = judgeSelectedSkill,
		judgeSupplementalSkills = judgeSupplementalSkills,
		judgeSelectedSkillGroup = judgeSelectedSkill and gemSummaryForSocketGroup(judgeSelectedSkill.groupIndex) or nil,
		mainSkillGroup = gems,
		notables = notables,
		keystones = keystones,
		ascendancyNotables = asc,
		gear = gear,
		customMods = (build.configTab and build.configTab.input.customMods) or "",
		attributes = {
			strength = asNumber(mainOutput.Str),
			dexterity = asNumber(mainOutput.Dex),
			intelligence = asNumber(mainOutput.Int),
		},
		attributeRequirements = {
			strength = asNumber(mainOutput.ReqStr),
			dexterity = asNumber(mainOutput.ReqDex),
			intelligence = asNumber(mainOutput.ReqInt),
		},
		spiritUsed = asNumber(mainOutput.SpiritReserved),
		spiritAvailable = asNumber(mainOutput.Spirit),
		spiritUnreserved = asNumber(mainOutput.SpiritUnreserved),
		pointsUsed = used,
		normalPassivePointsUsed = normalPassiveUsed,
		pointsAvailable = avail,
		unspentPoints = unspent,
		ascendancyPointsUsed = ascUsed,
		ascendancyPointsMax = ASCENDANCY_POINT_MAX,
		secondaryAscendancyPointsUsed = secondaryAscUsed,
		socketPointsUsed = socketsUsed,
		weaponSet1PointsUsed = weaponSet1Used,
		weaponSet2PointsUsed = weaponSet2Used,
		weaponSetPointsAvailable = weaponSetAvail,
		skillGroupCount = #(build.skillsTab.socketGroupList or {}),
		stats = collectStats(),
	}
	-- The ascendancy pool is capped at 8 in PoE2; an over-allocated tree is illegal in game.
	if ascUsed > ASCENDANCY_POINT_MAX then
		r.ascendancyNote = "Ascendancy is OVER budget: "
			.. ascUsed
			.. " allocated but only "
			.. ASCENDANCY_POINT_MAX
			.. " ascendancy points exist — this build is not legal in game. Deallocate "
			.. (ascUsed - ASCENDANCY_POINT_MAX)
			.. " ascendancy node(s)."
	end
	-- An export with many unspent points reads to users as "missing" tree/campaign points; flag
	-- it so the assistant spends them (or explains why they're parked).
	if unspent > 3 then
		r.pointsNote = unspent
			.. " passive points are unspent (available "
			.. avail
			.. ", used "
			.. normalPassiveUsed
			.. "). Allocate them (optimize_passives / alloc_passive) or tell the user why "
			.. "they're parked — an export with unspent points looks incomplete."
	end
	local note = dpsNoteFor((build.calcsTab and build.calcsTab.mainOutput) or {})
	if note then
		r.dpsNote = note
	end
	return r
end

-- Enumerate PoB configuration options usable with set_config (filterable).
function methods.list_config_options(p)
	p = p or {}
	local q = tostring(p.query or ""):lower()
	local limit = p.limit or 60
	local varList = LoadModule("Modules/ConfigOptions")
	local out = {}
	for _, v in ipairs(varList) do
		if type(v) == "table" and v.var then
			local label = (v.label or ""):gsub("%^x%x%x%x%x%x%x", ""):gsub("%^%d", "")
			if q == "" or label:lower():find(q, 1, true) or v.var:lower():find(q, 1, true) then
				local entry = { var = v.var, type = v.type, label = label }
				if v.list then
					local vals = {}
					for _, o in ipairs(v.list) do
						table.insert(vals, o.val)
					end
					entry.values = vals
				end
				table.insert(out, entry)
				if #out >= limit then
					break
				end
			end
		end
	end
	return { count = #out, options = out }
end

-- Defensive summary. Elemental resists include PoB's area resistance penalty; the note
-- reports the *actual* penalty currently applied (default is Endgame -60% when unset).
function methods.get_defenses()
	local o = (build.calcsTab and build.calcsTab.mainOutput) or {}
	local function n(k)
		return type(o[k]) == "number" and o[k] or nil
	end
	-- PoB applies configInput.resistancePenalty as a BASE to each elemental resist,
	-- falling back to -60 (Endgame) when the config is unset (see CalcSetup.lua).
	local cfg = (build.configTab and build.configTab.input) or {}
	local penalty = cfg.resistancePenalty or -60
	return {
		life = n("Life"),
		energyShield = n("EnergyShield"),
		mana = n("Mana"),
		ward = n("Ward"),
		armour = n("Armour"),
		evasion = n("Evasion"),
		blockChance = n("BlockChance"),
		spellBlockChance = n("SpellBlockChance"),
		resistances = {
			fire = n("FireResist"),
			cold = n("ColdResist"),
			lightning = n("LightningResist"),
			chaos = n("ChaosResist"),
		},
		resistOverCap = {
			fire = n("FireResistOverCap"),
			cold = n("ColdResistOverCap"),
			lightning = n("LightningResistOverCap"),
		},
		-- Points BELOW the (real, raisable) cap per element, 0 when capped. PoB floors *ResistOverCap
		-- at 0 so it can't reveal an UNDER-cap resist; this is the missing-to-cap gap (cap - final,
		-- using PoB's actual per-element max), so callers like optimize_item can detect a broken cap.
		resistMissing = {
			fire = n("MissingFireResist"),
			cold = n("MissingColdResist"),
			lightning = n("MissingLightningResist"),
		},
		resistPenalty = penalty,
		totalEHP = n("TotalEHP"),
		note = ("Elemental resistances are shown net of PoB's configured area penalty "
			.. "(resistancePenalty = %d%%; PoB's Endgame default is -60%%, earlier acts smaller). "
			.. "The cap is 75%% — raise resists toward it with gear/tree; over-cap buffers "
			.. "penetration and curses. Adjust with set_config({resistancePenalty = -60})."):format(
			penalty
		),
	}
end

-- ---------------------------------------------------------------------------
-- passive tree
-- ---------------------------------------------------------------------------
local function nodeSummary(n)
	return {
		id = n.id,
		name = n.name,
		type = n.type,
		stats = n.sd,
		alloc = n.alloc or false,
		pathDist = n.pathDist,
		ascendancy = n.ascendancyName,
	}
end

local function findNode(key)
	local spec = build.spec
	if not spec or key == nil then return nil end
	if spec.nodes[key] then return spec.nodes[key] end
	if type(key) == "string" then
		local asnum = tonumber(key)
		if asnum and spec.nodes[asnum] then return spec.nodes[asnum] end
		local lname = key:lower()
		local best
		for _, node in pairs(spec.nodes) do
			if node.name and node.name:lower() == lname then
				if node.alloc then return node end
				if node.path and (not best or (node.pathDist or 1e9) < (best.pathDist or 1e9)) then
					best = node
				elseif not best then
					best = node
				end
			end
		end
		return best
	end
	return nil
end

local function statSnapshot()
	local out = (build.calcsTab and build.calcsTab.mainOutput) or {}
	local snap = {}
	for _, k in ipairs(DEFAULT_STATS) do
		if type(out[k]) == "number" then snap[k] = out[k] end
	end
	return snap
end

local function statDelta(before)
	local snap = statSnapshot()
	local delta = {}
	for k, v in pairs(snap) do
		local d = v - (before[k] or 0)
		if math.abs(d) > 1e-9 then delta[k] = d end
	end
	return delta
end

function methods.search_passives(p)
	p = p or {}
	local terms = {}
	for t in tostring(p.query or ""):lower():gmatch("%w+") do
		terms[#terms + 1] = t
	end
	local wantType = p.node_type
	local limit = p.limit or 30
	-- Rank by how many query terms match (name + ascendancy + stat text), so multi-word and
	-- conceptual queries return the best partial matches instead of nothing. No query => browse.
	local scored = {}
	for _, node in pairs(build.spec.nodes) do
		if node.name and node.type ~= "ClassStart" and node.type ~= "AscendClassStart" then
			if (not wantType) or node.type == wantType then
				local hay = node.name:lower()
				if node.ascendancyName then
					hay = hay .. " " .. node.ascendancyName:lower()
				end
				if node.sd then
					hay = hay .. " " .. table.concat(node.sd, " "):lower()
				end
				local score = 0
				for _, t in ipairs(terms) do
					if hay:find(t, 1, true) then
						score = score + 1
					end
				end
				if #terms == 0 or score > 0 then
					scored[#scored + 1] = { node = node, score = score }
				end
			end
		end
	end
	-- most matched terms first, then reachable (lowest pathDist), then name for a stable order
	table.sort(scored, function(a, b)
		if a.score ~= b.score then
			return a.score > b.score
		end
		local pa, pb = a.node.pathDist or 1e9, b.node.pathDist or 1e9
		if pa ~= pb then
			return pa < pb
		end
		return (a.node.name or "") < (b.node.name or "")
	end)
	local res = {}
	for i = 1, math.min(limit, #scored) do
		res[#res + 1] = nodeSummary(scored[i].node)
	end
	return { results = res }
end

function methods.get_passive(p)
	local n = findNode(p and p.node)
	if not n then return { found = false } end
	local s = nodeSummary(n)
	s.found = true
	return s
end

function methods.alloc_passive(p)
	local n = findNode(p and p.node)
	if not n then return { ok = false, error = "node not found" } end
	if n.alloc then return { ok = true, already = true, node = nodeSummary(n) } end
	if not n.path then return { ok = false, error = "node not reachable from current tree" } end
	local before = statSnapshot()
	local used = build.spec:CountAllocNodes()
	build.spec:AllocNode(n, nil)
	build.buildFlag = true
	runCallback("OnFrame")
	local usedAfter = build.spec:CountAllocNodes()
	local r = {
		ok = true,
		node = nodeSummary(n),
		pointsSpent = usedAfter - used,
		statsDelta = statDelta(before),
	}
	-- Warn if this pushed the tree past the level's point budget (the build is now invalid until
	-- you free points or level up) — otherwise over-allocation is silent.
	local avail = availablePoints()
	if usedAfter > avail then
		r.warning = "Tree is over budget: "
			.. usedAfter
			.. " points allocated but only "
			.. avail
			.. " available at level "
			.. (build.characterLevel or 0)
			.. ". Free "
			.. (usedAfter - avail)
			.. " (dealloc_passive) or raise the level before exporting."
	end
	return r
end

function methods.dealloc_passive(p)
	local n = findNode(p and p.node)
	if not n then return { ok = false, error = "node not found" } end
	if not n.alloc then return { ok = false, error = "node not allocated" } end
	local before = statSnapshot()
	local used = build.spec:CountAllocNodes()
	build.spec:DeallocNode(n)
	build.buildFlag = true
	runCallback("OnFrame")
	local usedAfter = build.spec:CountAllocNodes()
	return {
		ok = true,
		node = nodeSummary(n),
		pointsFreed = used - usedAfter,
		statsDelta = statDelta(before),
	}
end

-- Greedy passive optimizer: repeatedly allocate the reachable node (+ its path) that most
-- improves the goal, using PoB's what-if calculator to score candidates without committing.
-- Supports a single `metric` (absolute gain), `goals` = {metric=weight} (weighted *relative*
-- gain — generalizes the "balanced" DPS+EHP mode), and `require` = nodes to allocate first.
function methods.optimize_passives(p)
	p = p or {}
	local metric = p.metric or "TotalDPS"
	local balanced = (metric == "balanced" or metric == "DPS+EHP")
	-- weighted goals: explicit p.goals, else balanced => equal-weight DPS+EHP, else single-metric.
	local goals = (type(p.goals) == "table") and p.goals or nil
	if not goals and balanced then
		goals = { TotalDPS = 1, TotalEHP = 1 }
	end
	local spec = build.spec
	-- `reset`: deallocate all REGULAR (non-ascendancy) nodes first so the tree is RE-PLANNED from
	-- scratch — e.g. to add jewel sockets — instead of accumulating on top of an already-full tree
	-- (which silently produced an over-budget, illegal tree). Ascendancy + class start are kept.
	if p.reset then
		local clear = {}
		for _, node in pairs(spec.allocNodes) do
			if
				node.type ~= "ClassStart"
				and node.type ~= "AscendClassStart"
				and not node.ascendancyName
			then
				clear[#clear + 1] = node
			end
		end
		for _, node in ipairs(clear) do
			if node.alloc then
				spec:DeallocNode(node)
			end
		end
		build.buildFlag = true
		runCallback("OnFrame")
	end
	local budget = p.points
	if not budget or budget <= 0 then
		budget = math.max(0, availablePoints() - spec:CountAllocNodes())
	end
	local cap = p.candidates or 50
	local chosen = {}

	-- metrics we will report start/final for
	local mo0 = build.calcsTab.mainOutput
	local reportKeys = {}
	if goals then
		for m in pairs(goals) do
			reportKeys[#reportKeys + 1] = m
		end
	else
		reportKeys[1] = metric
	end
	local startVals = {}
	for _, m in ipairs(reportKeys) do
		startVals[m] = (mo0[m]) or 0
	end

	-- `require`: allocate the named nodes (+ shortest path) before optimizing. This RE-PLANS the tree
	-- around them, so it only makes sense on a FRESH tree — requiring nodes on top of an already-full
	-- tree silently over-allocates into an illegal (>budget) tree (the footgun). So: if regular nodes
	-- are already allocated and `reset` wasn't asked, skip the requires + tell the caller to reset.
	-- On a fresh/reset tree pathDist is the true point cost, so we cap allocation to the budget.
	local requiredSpent = 0
	local requireSkipped = {}
	if type(p.require) == "table" and #p.require > 0 then
		if spec:CountAllocNodes() > 0 and not p.reset then
			for _, ref in ipairs(p.require) do
				local n = findNode(ref)
				requireSkipped[#requireSkipped + 1] = (n and n.name) or tostring(ref)
			end
		else
			for _, ref in ipairs(p.require) do
				local n = findNode(ref)
				if n and not n.alloc and n.path then
					if (n.pathDist or 1) <= (budget - requiredSpent) then
						local u0 = spec:CountAllocNodes()
						spec:AllocNode(n, nil)
						build.buildFlag = true
						runCallback("OnFrame")
						requiredSpent = requiredSpent + (spec:CountAllocNodes() - u0)
						chosen[#chosen + 1] = { name = n.name, id = n.id, required = true }
					else
						requireSkipped[#requireSkipped + 1] = n.name or tostring(ref)
					end
				end
			end
		end
		budget = math.max(0, budget - requiredSpent)
	end

	-- weighted relative gain across goals (so DPS in thousands and CritChance 0-100 combine), or
	-- plain absolute gain for a single metric.
	local function scoreGain(calcBase, out)
		if goals then
			local g = 0
			for m, w in pairs(goals) do
				local b = (calcBase[m]) or 0
				local v = (out[m]) or 0
				if b > 0 then
					g = g + w * (v - b) / b
				else
					g = g + w * (v - b) * 1e-4 -- base 0 (e.g. crit on a non-crit build): tiny nudge
				end
			end
			return g
		end
		return ((out[metric]) or 0) - ((calcBase[metric]) or 0)
	end

	-- One greedy pass over a single node type until nothing helps or the budget runs out.
	local function greedyPass(nodeType, budgetLeft)
		local spent = 0
		while budgetLeft > 0 do
			local _, ascUsed = spec:CountAllocNodes() -- ascendancy uses a SEPARATE 8-point pool
			local calcFunc, calcBase = build.calcsTab:GetMiscCalculator(build)
			local cands = {}
			for _, node in pairs(spec.nodes) do
				if not node.alloc and node.path and node.type == nodeType and node.pathDist then
					-- Each node must fit its OWN budget: ascendancy nodes the 8-point ascendancy pool,
					-- regular nodes the passive budget — ascendancy must NOT consume passive points
					-- (charging it to the passive budget both stranded passive points and let the
					-- greedy allocate an illegal >8-point ascendancy).
					local fits
					if node.ascendancyName then
						fits = (ascUsed + node.pathDist) <= ASCENDANCY_POINT_MAX
					else
						fits = node.pathDist <= budgetLeft
					end
					if fits then
						cands[#cands + 1] = node
					end
				end
			end
			-- Stable total order (pathDist, then id) so the greedy is deterministic — `pairs` order
			-- is unspecified and otherwise drifts between LuaJIT builds/platforms (local vs CI).
			table.sort(cands, function(a, b)
				local pa, pb = a.pathDist or 1e9, b.pathDist or 1e9
				if pa ~= pb then
					return pa < pb
				end
				return (a.id or 0) < (b.id or 0)
			end)

			local best, bestGain, bestCost
			for i = 1, math.min(#cands, cap) do
				local node = cands[i]
				local pathNodes = {}
				for _, pn in ipairs(node.path) do
					pathNodes[pn] = true
				end
				pathNodes[node] = true
				local gain = scoreGain(calcBase, calcFunc({ addNodes = pathNodes }))
				if gain > 0 and (not best or gain > bestGain) then
					best, bestGain, bestCost = node, gain, node.pathDist
				end
			end

			if not best then
				break
			end
			spec:AllocNode(best, nil)
			build.buildFlag = true
			runCallback("OnFrame")
			chosen[#chosen + 1] =
				{ name = best.name, id = best.id, cost = bestCost, gain = bestGain, type = nodeType }
			-- Only regular passives draw down the passive budget; ascendancy nodes spend the separate
			-- ascendancy pool (capped above), so allocating them never strands passive points.
			if not best.ascendancyName then
				spent = spent + bestCost
				budgetLeft = budgetLeft - bestCost
			end
		end
		return spent
	end

	local nodeType = p.node_type or "Notable"
	local used = greedyPass(nodeType, budget)
	budget = budget - used
	-- If filling the default (Notables), spend leftover budget on small (Normal) nodes too, so the
	-- tree isn't left point-starved — the common cause of "missing points" in exports.
	local smallUsed = 0
	if budget > 0 and nodeType == "Notable" then
		smallUsed = greedyPass("Normal", budget)
		used = used + smallUsed
		budget = budget - smallUsed
	end
	used = used + requiredSpent

	local mo1 = build.calcsTab.mainOutput
	-- TRUE unspent PASSIVE points on the build (not the local greedy budget) so a capped `points`
	-- call never misreads as "fully allocated" when the tree still has points free. (Ascendancy is a
	-- separate pool, reported elsewhere.)
	local unspent = math.max(0, availablePoints() - (spec:CountAllocNodes()))
	local result = {
		metric = p.goals and "weighted" or metric,
		pointsUsed = used,
		pointsRemaining = unspent,
		smallNodePoints = smallUsed,
		requiredPoints = requiredSpent,
		allocated = chosen,
	}
	-- Required nodes that didn't fit the budget (would have over-allocated the tree) — surface them
	-- so the caller knows to free points or pass reset=true, rather than silently shipping an
	-- illegal over-budget tree.
	if #requireSkipped > 0 then
		result.requireSkipped = requireSkipped
		result.requireNote = #requireSkipped
			.. " required node(s) didn't fit the passive budget and were skipped (the tree would be "
			.. "over-budget). Free points first or pass reset=true to re-plan the tree from scratch."
	end
	if used - requiredSpent == 0 and unspent > 0 then
		result.note = "The optimizer allocated NOTHING — no reachable node improved the goal, though "
			.. unspent
			.. " passive points are unspent. Likely the metric doesn't scale off the passive tree for "
			.. "this skill (e.g. an uncomputable / placeholder-damage skill — verify with "
			.. "explain_mechanic / relevant_mechanics), or the reachable nodes simply don't move it."
	elseif unspent > 5 then
		result.note = unspent
			.. " passive points still unspent — either raise `points` (it caps allocation; pass 0 for "
			.. "the whole tree), try different goals/weights or node_type, or alloc_passive toward a "
			.. "specific cluster; otherwise they're parked for later gear/scaling (say so)."
	end
	-- start/final for every reported metric
	local metricsOut = {}
	for _, m in ipairs(reportKeys) do
		metricsOut[m] = { start = startVals[m], final = (mo1[m]) or startVals[m] }
	end
	result.metrics = metricsOut
	-- back-compat fields
	if goals and goals.TotalDPS and goals.TotalEHP then
		result.startDPS, result.finalDPS = startVals.TotalDPS, (mo1.TotalDPS) or startVals.TotalDPS
		result.startEHP, result.finalEHP = startVals.TotalEHP, (mo1.TotalEHP) or startVals.TotalEHP
	elseif not goals then
		result.startValue = startVals[metric]
		result.finalValue = (mo1[metric]) or startVals[metric]
	end
	return result
end

-- ---------------------------------------------------------------------------
-- RPC loop
-- ---------------------------------------------------------------------------
emit(json.encode({ ready = true, jit = jit and jit.version, treeVersion = latestTreeVersion }))

for line in io.lines() do
	line = line:gsub("[\r\n]+$", "")
	if #line > 0 then
		local req = json.decode(line)
		local id = req and req.id
		local fn = req and methods[req.method]
		if not req then
			emit(json.encode({ ok = false, error = "malformed request" }))
		elseif not fn then
			emit(json.encode({ id = id, ok = false, error = "unknown method: " .. tostring(req.method) }))
		else
			local ok, result = pcall(fn, req.params or {})
			if ok then
				emit(json.encode({ id = id, ok = true, result = result }))
			else
				emit(json.encode({ id = id, ok = false, error = tostring(result) }))
			end
		end
	end
end
