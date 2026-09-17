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
local HEADLESS_RUNTIME_CONTRACT = 15

-- Boot the engine (its prints now land on stderr).
local booted, bootErr = pcall(dofile, "HeadlessWrapper.lua")
if not booted or not build then
	emit(json.encode({ ready = false, error = "engine init failed: " .. tostring(bootErr) }))
	os.exit(1)
end

-- GUI-sized GC pauses let native what-if calculations accumulate gigabytes of dead tables
-- during long headless searches. Reclaim only unreachable objects at safe calculation boundaries;
-- do not discard live PoB caches, alter the build, or reduce the candidate search space.
local GC_GROWTH_KB = 128 * 1024
local gcCollections = 0
collectgarbage("collect")
local nextGcKB = collectgarbage("count") + GC_GROWTH_KB
local function reclaimCalculationGarbage()
	if collectgarbage("count") >= nextGcKB then
		collectgarbage("collect")
		gcCollections = gcCollections + 1
		nextGcKB = collectgarbage("count") + GC_GROWTH_KB
	end
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

local function asOptionalNumber(v)
	if type(v) == "number" then
		return v
	elseif type(v) == "string" then
		return tonumber(v)
	elseif type(v) == "boolean" then
		return v and 1 or 0
	end
	return nil
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

-- CalcDefence derives this flag from the active player's modDB, including granted keystones.
-- FlagInternal returns nil when absent; only a calculated player output can prove absence.
local function defenseMechanics(out)
	local observed = type(out) == "table" and type(out.Life) == "number"
	local result = {
		schemaVersion = 1,
		source = "pob_main_output",
		status = observed and "observed" or "unavailable",
	}
	if observed then result.chaosInoculation = out.ChaosInoculation == true end
	return result
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

-- Only PoB's synthesized first gem, bound to the currently equipped item and its
-- exact parsed grant, may use an item-granted level instead of the gem level cap.
-- XML source labels and caller-supplied gem metadata are not source authority.
local function itemGrantedLevelForSocketGroup(sg, gem)
	if not sg or not gem or gem.fromItem ~= true or sg.gemList[1] ~= gem then
		return nil
	end
	local item = sg.sourceItem
	local slot = sg.slot and build.itemsTab.slots[sg.slot]
	if not item or not slot or build.itemsTab.items[slot.selItemId] ~= item then
		return nil
	end
	for _, grant in ipairs(item.grantedSkills or {}) do
		if grant.source == sg.source and grant.skillId == gem.skillId then
			local effect = build.data.skills[grant.skillId]
			if effect and effect.levels and next(effect.levels) ~= nil then
				-- PoB normalizes sparse item effects (e.g. a logical level 1 grant
				-- with only a level 20 model). Reuse that exact read-only routine.
				local normalized = { grantedEffect = effect, level = grant.level }
				calcLib.validateGemLevel(normalized)
				-- Native PoB can lower an item grant for current character/attribute
				-- requirements. Its real modeled level remains authorized only under
				-- this exact equipped source's normalized upper bound.
				if asNumber(gem.level) > 0 and gem.level <= normalized.level and effect.levels[gem.level] then
					return asNumber(gem.level)
				end
			end
		end
	end
	return nil
end

-- Default attacks are regenerated by PoB for each real weapon set. A saved XML
-- source label is insufficient: bind the root to the current MAIN calculation's
-- native grant, including slot, effect and normalized level.
local function defaultAttackLevelForSocketGroup(sg)
	local gem = sg and sg.gemList and sg.gemList[1]
	local env = build.calcsTab and build.calcsTab.mainEnv
	if not gem or sg.source ~= "Default Attack" or sg.sourceItem or sg.sourceNode
		or gem.fromItem ~= true or not env then
		return nil
	end
	for _, grant in ipairs(env.grantedSkills or {}) do
		if grant.source == "Default Attack" and not grant.sourceItem and not grant.sourceNode
			and grant.slotName == sg.slot and grant.skillId == gem.skillId then
			local effect = build.data.skills[grant.skillId]
			if effect and effect.levels then
				local normalized = { grantedEffect = effect, level = grant.level }
				calcLib.validateGemLevel(normalized)
				if normalized.level == gem.level and effect.levels[gem.level] then
					return asNumber(normalized.level)
				end
			end
		end
	end
	return nil
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
				local naturalMaxLevel = g.gemData and asNumber(g.gemData.naturalMaxLevel) or 0
				local levelData = ge and ge.levels and ge.levels[asNumber(g.level)] or nil
				local requiredLevel = levelData and asNumber(levelData.levelRequirement) or nil
				local itemGrantedLevel = not isSupport and itemGrantedLevelForSocketGroup(sg, g) or nil
				local defaultAttackLevel = not isSupport and sg.gemList[1] == g and defaultAttackLevelForSocketGroup(sg) or nil
				local unverifiedItemGrant = not isSupport and g.fromItem == true and not itemGrantedLevel and not defaultAttackLevel
				local maximumLegalLevel = nil
				if itemGrantedLevel then
					maximumLegalLevel = requiredLevel and requiredLevel <= asNumber(build.characterLevel)
						and itemGrantedLevel or 0
				elseif ge and ge.levels and naturalMaxLevel > 0 then
					maximumLegalLevel = 0
					for level = 1, naturalMaxLevel do
						local candidate = ge.levels[level]
						if candidate and asNumber(candidate.levelRequirement) <= asNumber(build.characterLevel) then
							maximumLegalLevel = level
						end
					end
				end
				local levelRequirementMet = true
				if not isSupport then
					if unverifiedItemGrant then
						levelRequirementMet = false
					elseif itemGrantedLevel then
						levelRequirementMet = requiredLevel ~= nil and requiredLevel <= asNumber(build.characterLevel)
					elseif requiredLevel == nil then
						levelRequirementMet = nil
					else
						levelRequirementMet = requiredLevel <= asNumber(build.characterLevel)
							and (naturalMaxLevel <= 0 or asNumber(g.level) <= naturalMaxLevel)
					end
				end
				table.insert(gems, {
					name = nm,
					gemId = g.gemId or (g.gemData and g.gemData.id),
					gameId = g.gemData and g.gemData.gameId,
					effectId = ge and ge.id,
					level = g.level,
					quality = g.quality,
					enabled = g.enabled ~= false,
					count = g.count,
					isSupport = isSupport and true or false,
					isActive = not isSupport,
					supportKnown = isSupport and true or false,
					requiredLevel = requiredLevel,
					naturalMaxLevel = naturalMaxLevel > 0 and naturalMaxLevel or nil,
					maximumLegalLevel = maximumLegalLevel,
					levelAuthority = itemGrantedLevel and "item_grant" or defaultAttackLevel and "default_attack" or unverifiedItemGrant and "unverified_item_grant" or "gem",
					levelRequirementMet = levelRequirementMet,
				})
			end
		end
	end
	return gems
end

local function activeGemLevelViolationsForSocketGroup(groupIndex)
	local violations = {}
	for _, gem in ipairs(gemSummaryForSocketGroup(groupIndex)) do
		if gem.isActive and gem.levelRequirementMet == false then
			local reason = "character_level_below_gem_requirement"
			if gem.levelAuthority == "unverified_item_grant" then
				reason = "item_granted_skill_source_unverified"
			elseif gem.levelAuthority == "item_grant" and gem.requiredLevel == nil then
				reason = "item_granted_skill_level_unmodelled"
			elseif gem.levelAuthority ~= "item_grant" and gem.naturalMaxLevel and asNumber(gem.level) > asNumber(gem.naturalMaxLevel) then
				reason = "base_gem_level_exceeds_natural_maximum"
			end
			violations[#violations + 1] = {
				groupIndex = groupIndex,
				name = gem.name,
				gemLevel = asNumber(gem.level),
				requiredLevel = gem.requiredLevel,
				characterLevel = asNumber(build.characterLevel),
				maximumLegalLevel = gem.maximumLegalLevel,
				naturalMaxLevel = gem.naturalMaxLevel,
				levelAuthority = gem.levelAuthority,
				reason = reason,
			}
		end
	end
	return violations
end

local function activeGemLevelViolations()
	local violations = {}
	for index, group in ipairs(build.skillsTab.socketGroupList or {}) do
		if group and group.enabled ~= false then
			for _, violation in ipairs(activeGemLevelViolationsForSocketGroup(index)) do
				violations[#violations + 1] = violation
			end
		end
	end
	return violations
end

-- Per-source attribute requirements (equipped items + enabled gems), so a hard-legality
-- shortfall can name WHO asks for the missing attribute instead of a single aggregated total.
local function attributeRequirementSources()
	local sources = {}
	local function push(source, kind, str, dex, int)
		local s, d, i = asNumber(str), asNumber(dex), asNumber(int)
		if s > 0 or d > 0 or i > 0 then
			sources[#sources + 1] = {
				source = source,
				kind = kind,
				strength = s,
				dexterity = d,
				intelligence = i,
			}
		end
	end
	for slotName, slot in pairs(build.itemsTab.slots) do
		local id = slot.selItemId
		if id and id ~= 0 and build.itemsTab.items[id] then
			local it = build.itemsTab.items[id]
			local req = it.requirements or {}
			push(
				"item:" .. slotName .. " (" .. (it.baseName or it.title or "?") .. ")",
				"item",
				req.str,
				req.dex,
				req.int
			)
		end
	end
	for index, group in ipairs(build.skillsTab.socketGroupList or {}) do
		if group and group.enabled ~= false then
			for _, gem in ipairs(group.gemList or {}) do
				local nm = gem.nameSpec
				if (not nm or nm == "") and gem.gemData and gem.gemData.grantedEffect then
					nm = gem.gemData.grantedEffect.name
				end
				if nm and nm ~= "" and gem.enabled ~= false then
					push(
						"gem:" .. nm .. " lvl" .. asNumber(gem.level),
						"gem",
						gem.reqStr,
						gem.reqDex,
						gem.reqInt
					)
				end
			end
		end
	end
	return sources
end

local function defaultGemLevelForCharacter(name)
	local lookupName = tostring(name or ""):lower()
	local gemId = build.data and build.data.gemForBaseName
		and (build.data.gemForBaseName[lookupName] or build.data.gemForBaseName[lookupName .. " support"])
	local gemData = gemId and build.data.gems and build.data.gems[gemId] or nil
	local grantedEffect = gemData and gemData.grantedEffect or nil
	if not gemData or not grantedEffect then
		return nil
	end
	if grantedEffect.support then
		return 1
	end
	local naturalMaxLevel = asNumber(gemData.naturalMaxLevel)
	local maximumLegalLevel = 0
	for level = 1, naturalMaxLevel do
		local levelData = grantedEffect.levels and grantedEffect.levels[level]
		if levelData and asNumber(levelData.levelRequirement) <= asNumber(build.characterLevel) then
			maximumLegalLevel = level
		end
	end
	return maximumLegalLevel > 0 and maximumLegalLevel or 1
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

local function isInternalJudgeSkillForm(skillName)
	local name = tostring(skillName or "")
	return name:match("^Load%s+") ~= nil or name:match("^Reload%s+") ~= nil
end

local function judgeSupplementalSkillSummaries()
	local list = build.skillsTab.socketGroupList or {}
	local supplemental = {}
	for index, sg in ipairs(list) do
		local origin = judgeSkillGroupOrigin(sg)
		if sg and sg.enabled ~= false and (origin == "synthetic_on_kill" or origin == "synthetic_reactive") then
			for activeIndex = 1, #(sg.displaySkillList or {}) do
				local summary = activeSkillSummary(index, activeIndex)
				supplemental[#supplemental + 1] = {
					groupIndex = index,
					activeIndex = activeIndex,
					skillName = summary.skillName,
					groupOrigin = origin,
					groupSource = summary.groupSource,
					socketLegalityApplicable = summary.socketLegalityApplicable,
					scenarioLimitations = summary.scenarioLimitations,
				}
			end
		end
	end
	return supplemental
end

-- Select exactly the player-facing skill requested by the Create/Judge contract.  This runs only
-- inside the disposable Judge engine: ordinary get_build readback must never scan or mutate skill
-- groups.  Internal crossbow actions such as "Load ..." and "Reload ..." are deliberately
-- excluded even when they expose a large PoB metric.
local function selectJudgeSkillForGroup(groupIndex, expectedSkillName)
	local list = build.skillsTab.socketGroupList or {}
	local index = tonumber(groupIndex)
	local expected = tostring(expectedSkillName or "")
	if not index or index < 1 or expected == "" or isInternalJudgeSkillForm(expected) then
		return nil
	end
	local sg = list[index]
	if not sg or sg.enabled == false or not sg.displaySkillList then
		return nil
	end
	for activeIndex = 1, #sg.displaySkillList do
		selectMainSocketGroup(index, activeIndex)
		local summary = activeSkillSummary(index, activeIndex)
		if summary.skillName == expected and not isInternalJudgeSkillForm(summary.skillName) then
			for otherIndex, other in ipairs(list) do
				other.includeInFullDPS = (otherIndex == index)
			end
			selectMainSocketGroup(index, activeIndex)
			runCallback("OnFrame")
			local out = (build.calcsTab and build.calcsTab.mainOutput) or {}
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
			if asNumber(out.ProjectileCount) > 1 and metric.key ~= "FullDPS" then
				caveats[#caveats + 1] = "projectile_overlap_unverified_caveat"
			end
			local candidate = {
				groupIndex = index,
				activeIndex = summary.activeIndex,
				skillName = summary.skillName,
				dps = effectiveValue,
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
			return candidate
		end
	end
	return nil
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
		local bareName = line:match("^%s*(.-)%s*$")
		if bareName ~= "" and not bareName:match("^%a+%s*:") and not bareName:match("%d+/%d+") then
			local defaultLevel = defaultGemLevelForCharacter(bareName)
			if defaultLevel then
				line = bareName .. " " .. defaultLevel .. "/20 1"
			end
		end
		if line:match("^%s*[%a':][%a':' ]* %d+/%d+%s*%u*%s*$") then
			line = line:gsub("%s*$", "") .. "  1"
		end
		lines[#lines + 1] = line
	end
	return table.concat(lines, "\n")
end

local function pasteSocketGroup(text)
	local normalized = normalizeSkillText(text)
	local extendedName = false
	for line in normalized:gmatch("([^\r\n]+)") do
		local name = line:match("^(.-) %d+/%d+%s*%u*%s+[%d%.]+%s*C?[+%-]?%d*%s*$")
		if name and not name:match("^[ %a':]+$") then extendedName = true end
	end
	if not extendedName then
		return build.skillsTab:PasteSocketGroup(normalized)
	end
	-- The pinned clipboard parser only admits ASCII letters, spaces, apostrophes
	-- and colons. Construct the same native group for exact catalog names containing
	-- other characters; never strip punctuation or guess a different gem identity.
	local group = { label = normalized:match("Label: (%C+)") or "", enabled = true, gemList = {} }
	group.slot = normalized:match("Slot: (%C+)")
	local weaponSet = normalized:match("Weapon Set: Set ([12])")
	if weaponSet then group.set1, group.set2 = weaponSet == "1", weaponSet == "2" end
	for line in normalized:gmatch("([^\r\n]+)") do
		local name, level, quality, state, count, cFlag, cLevel =
			line:match("^(.-) (%d+)/(%d+)%s*(%u*)%s+([%d%.]+)%s*(C?)([+%-]?%d*)%s*$")
		if name then
			local gemId = build.data.gemForBaseName[name:lower()]
				or build.data.gemForBaseName[name:lower() .. " support"]
			local gem = gemId and build.data.gems[gemId]
			if not gem or not gem.name or gem.name:lower() ~= name:lower() then return end
			group.gemList[#group.gemList + 1] = {
				nameSpec = gem.name, gemId = gemId,
				level = tonumber(level), quality = tonumber(quality), count = tonumber(count),
				enabled = state ~= "DISABLED", corrupted = cFlag == "C",
				corruptLevel = tonumber(cLevel) or 0, enableGlobal1 = true, enableGlobal2 = true,
			}
		elseif not line:match("^Label: ") and not line:match("^Slot: ")
			and not line:match("^Weapon Set: Set [12]$") then
			return -- Preserve the all-or-nothing boundary on malformed extended requests.
		end
	end
	if #group.gemList == 0 then return end
	local tab = build.skillsTab
	table.insert(tab.socketGroupList, group)
	tab.controls.groupList.selIndex, tab.controls.groupList.selValue = #tab.socketGroupList, group
	tab:SetDisplayGroup(group)
	tab:AddUndoState()
	tab.build.buildFlag = true
end

function selectMainSocketGroup(index, activeIndex)
	index = index or 1
	local sg = build.skillsTab.socketGroupList[index]
	local active = activeIndex or 1
	-- Callers can update a group's selection before arriving here. Always rebuild after an
	-- explicit selection mutation; read-only context verification avoids calling this helper.
	build.mainSocketGroup = index
	if sg then
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

local function skillGroupState()
	local groups = {}
	local list = build.skillsTab.socketGroupList or {}
	for index, group in ipairs(list) do
		local activeSkills = {}
		for activeIndex, _ in ipairs(group.displaySkillList or {}) do
			local active = group.displaySkillList[activeIndex]
			activeSkills[#activeSkills + 1] = {
				index = activeIndex,
				name = skillNameAt(index, activeIndex),
				effectId = active.activeEffect and active.activeEffect.grantedEffect and active.activeEffect.grantedEffect.id,
				effectiveLevel = active.activeEffect and active.activeEffect.level,
			}
		end
		groups[#groups + 1] = {
			index = index,
			label = group.label or "",
			slot = group.slot,
			enabled = group.enabled ~= false,
			includeInFullDPS = group.includeInFullDPS and true or false,
			groupCount = group.groupCount,
			source = group.source,
			sourceKind = group.sourceItem and "item" or group.sourceNode and "tree"
				or defaultAttackLevelForSocketGroup(group) and "default_attack" or group.source and "other" or nil,
			rootSkillId = group.gemList and group.gemList[1] and group.gemList[1].skillId or nil,
			mutable = group.source == nil,
			noSupports = (
				group.noSupports
				or (group.gemList and group.gemList[1] and group.gemList[1].noSupports)
			) and true or false,
			isMain = index == (build.mainSocketGroup or 1),
			mainActiveSkill = group.mainActiveSkill or 1,
			mainActiveSkillCalcs = group.mainActiveSkillCalcs or group.mainActiveSkill or 1,
			activeSkill = skillNameAt(index, group.mainActiveSkill or 1),
			activeSkills = activeSkills,
			gems = gemSummaryForSocketGroup(index),
		}
	end
	return {
		mainGroupIndex = build.mainSocketGroup or 1,
		calcsGroupIndex = build.calcsTab and build.calcsTab.input and build.calcsTab.input.skill_number or nil,
		groups = groups,
	}
end

local function sourceSupportCapacity(level)
	level = asNumber(level)
	if level >= 20 then return 5 end
	if level >= 15 then return 4 end
	if level >= 10 then return 3 end
	return 2
end

local function spiritState()
	local output = (build.calcsTab and build.calcsTab.mainOutput) or {}
	local available = asOptionalNumber(output.Spirit)
	local unreserved = asOptionalNumber(output.SpiritUnreserved)
	return {
		available = available,
		reserved = asOptionalNumber(output.SpiritReserved),
		unreserved = unreserved,
		requested = available and unreserved and (available - unreserved) or nil,
		overBy = unreserved and math.max(0, -unreserved) or nil,
	}
end

local function supportApplicationForGroup(group)
	-- A support-granted effect cannot establish its own host. Start with native active
	-- effects, then admit grants only after their owning support affects a reachable host.
	-- This also rejects mutually dependent grants while preserving anchored support chains.
	local activeList = group.displaySkillList or {}
	local reachable, owners, supportGems, applied = {}, {}, {}, {}
	for activeIndex, active in ipairs(activeList) do
		local effect = active.activeEffect
		local source = effect and effect.srcInstance
		local sourceEffect = source and ((source.gemData and source.gemData.grantedEffect) or source.grantedEffect)
		if sourceEffect and sourceEffect.support then
			owners[activeIndex] = source
		elseif effect and effect.grantedEffect and not hasType(effect.grantedEffect, "SkillGrantedBySupport") then
			reachable[activeIndex] = true
		end
	end
	for _, gem in ipairs(group.gemList or {}) do
		local ge = (gem.gemData and gem.gemData.grantedEffect) or gem.grantedEffect
		if ge and ge.support then
			supportGems[#supportGems + 1] = { gem = gem, effect = ge }
			applied[gem] = {}
			for activeIndex, active in ipairs(activeList) do
				local activeGe = active.activeEffect and active.activeEffect.grantedEffect
				-- effectList contains only effects actually applied to this precise active.
				for _, effect in ipairs(active.effectList or {}) do
					if activeGe and effect.srcInstance == gem and effect.grantedEffect
						and effect.grantedEffect.id == ge.id and effect.supportedActiveEffectIds
						and effect.supportedActiveEffectIds[activeGe.id] then
						applied[gem][activeIndex] = true
					end
				end
			end
		end
	end
	local licensed, changed = {}, true
	while changed do
		changed = false
		for _, support in ipairs(supportGems) do
			if not licensed[support.gem] then
				for activeIndex in pairs(applied[support.gem]) do
					if reachable[activeIndex] then
						licensed[support.gem] = true
						changed = true
						break
					end
				end
			end
		end
		for activeIndex, owner in pairs(owners) do
			if licensed[owner] and not reachable[activeIndex] then
				reachable[activeIndex] = true
				changed = true
			end
		end
	end
	local application = {}
	for _, support in ipairs(supportGems) do
		local names, rootedIds, unrootedIds = {}, {}, {}
		for activeIndex, active in ipairs(activeList) do
			if applied[support.gem][activeIndex] then
				local ge = active.activeEffect.grantedEffect
				if reachable[activeIndex] then
					names[#names + 1] = ge.name
					rootedIds[#rootedIds + 1] = ge.id
				else
					unrootedIds[#unrootedIds + 1] = ge.id
				end
			end
		end
		application[#application + 1] = {
			name = support.gem.nameSpec or "",
			supportEffectId = support.effect.id,
			activeSkills = names,
			rootedActiveEffectIds = rootedIds,
			unrootedActiveEffectIds = unrootedIds,
		}
	end
	return application
end

-- ---------------------------------------------------------------------------
-- methods
-- ---------------------------------------------------------------------------
local methods = {}

function methods.ping()
	reclaimCalculationGarbage()
	return {
		pong = true, jit = jit and jit.version,
		luaMemoryKB = collectgarbage("count"), gcCollections = gcCollections,
	}
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
	pasteSocketGroup(p.text)
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
	if prevMain and prevMain >= 1 and prevMain <= before and prevMain ~= newIndex
		and not list[prevMain].source then
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
	local levelViolations = activeGemLevelViolationsForSocketGroup(newIndex)
	-- A pristine PoB starts at level 1 and many compute callers set a skill before they initialise
	-- the character shell. Preserve that setup order, but the resulting snapshot is still blocked by
	-- completeness/Judge until its character level is made legal.
	if #levelViolations > 0 and asNumber(build.characterLevel) > 1 then
		loadBuildFromXML(snapshot)
		runCallback("OnFrame")
		return {
			ok = false,
			errorCode = "active_skill_gem_level_requirement_unmet",
			error = "an active gem level exceeds the current character-level requirement; "
				.. "use the reported maximumLegalLevel or omit the level for an automatic legal default",
			violations = levelViolations,
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
	local snapshot = build:SaveDB("code")
	local previousMain = list[build.mainSocketGroup or 1]
	local function selectedEffectId(group, field)
		local active = group and group.displaySkillList and group.displaySkillList[group[field] or group.mainActiveSkill or 1]
		return active and active.activeEffect and active.activeEffect.grantedEffect and active.activeEffect.grantedEffect.id
	end
	local previousSelections = {
		mainActiveSkill = selectedEffectId(previousMain, "mainActiveSkill"),
		mainActiveSkillCalcs = selectedEffectId(previousMain, "mainActiveSkillCalcs"),
	}
	local before = #list
	pasteSocketGroup(p.text)
	if #list <= before then
		loadBuildFromXML(snapshot)
		runCallback("OnFrame")
		return {
			ok = false,
			error = "no gem could be parsed from the skill text; build left unchanged",
			mainSkill = mainSkillName(),
		}
	end
	local addedGroup = list[before + 1]
	local levelViolations = {}
	for index = before + 1, #list do
		for _, violation in ipairs(activeGemLevelViolationsForSocketGroup(index)) do
			levelViolations[#levelViolations + 1] = violation
		end
	end
	if #levelViolations > 0 and asNumber(build.characterLevel) > 1 then
		loadBuildFromXML(snapshot)
		runCallback("OnFrame")
		return {
			ok = false,
			errorCode = "active_skill_gem_level_requirement_unmet",
			error = "an active gem level exceeds the current character-level requirement; "
				.. "use the reported maximumLegalLevel or omit the level for an automatic legal default",
			violations = levelViolations,
			mainSkill = mainSkillName(),
		}
	end
	-- Optionally include a second DAMAGE skill in FullDPS (clear+boss, triggers). Off by default so
	-- auras/heralds/buffs don't inflate the combined number.
	if p.includeInFullDPS then
		for i = before + 1, #list do
			list[i].includeInFullDPS = true
		end
	end
	runCallback("OnFrame")
	-- Native source reconciliation preserves main/calcs group identity while it may
	-- remove an old generated group and adopt the pasted loadout. Never restore an
	-- obsolete numeric index (or reset its selected active effect).
	local currentMain = build.skillsTab.socketGroupList[build.mainSocketGroup or 1]
	if previousMain and currentMain ~= previousMain then
		if not currentMain or not previousMain.source or currentMain.source ~= previousMain.source
			or currentMain.slot ~= previousMain.slot then
			loadBuildFromXML(snapshot)
			runCallback("OnFrame")
			return { ok = false, errorCode = "main_skill_identity_changed", error = "main skill source changed; build restored" }
		end
		for field, effectId in pairs(previousSelections) do
			local matchedIndex
			for activeIndex, active in ipairs(currentMain.displaySkillList or {}) do
				if active.activeEffect and active.activeEffect.grantedEffect.id == effectId then
					if matchedIndex then matchedIndex = nil; break end
					matchedIndex = activeIndex
				end
			end
			if not matchedIndex then
				loadBuildFromXML(snapshot)
				runCallback("OnFrame")
				return { ok = false, errorCode = "main_skill_effect_changed", error = "main skill effect was lost or ambiguous; build restored" }
			end
			currentMain[field] = matchedIndex
		end
		build.buildFlag = true
		build.modFlag = true
		runCallback("OnFrame")
	end
	for index, group in ipairs(build.skillsTab.socketGroupList or {}) do
		if group == addedGroup then
			local result = statResult(p.keys)
			result.groupIndex = index
			return result
		end
	end
	loadBuildFromXML(snapshot)
	runCallback("OnFrame")
	return { ok = false, errorCode = "skill_group_not_preserved", error = "PoB did not preserve the pasted group; build restored" }
end

function methods.list_skill_groups()
	return skillGroupState()
end

-- Research-only native reservation projection. Never selects a skill, runs a frame,
-- merges groups, or re-evaluates reservation formulas. Runtime identities refer to
-- the post-import snapshot, not to an inferred original-source container.
do
	local function numberOrNull(value)
		if type(value) == "number" and value == value and value ~= math.huge and value ~= -math.huge then
			return value
		end
		return json.null
	end
	local function valueOrNull(value)
		return value ~= nil and value or json.null
	end
	function methods.inspect_reservation_ledger()
		local env = build.calcsTab and build.calcsTab.mainEnv
		local actor = env and env.player
		if not actor or not actor.output or not actor.activeSkillList then
			return { schemaVersion = "pob_reservation_ledger_v1", status = "unavailable", reason = "native_actor_unavailable" }
		end
		local pools = { "Life", "Mana", "Spirit" }
		local result = {
			schemaVersion = "pob_reservation_ledger_v1", status = "available",
			identityScope = "post_import_runtime", valueScope = "native_calculated_reservation",
			activeWeaponSet = build.itemsTab.activeItemSet.useSecondWeaponSet and 2 or 1,
			actorWeaponSet = numberOrNull(env.weaponSet),
			groups = {}, effects = {}, totals = {},
			sourceGroupMappingStatus = "not_observed",
			limitations = {
				"Absent numeric fields are unknown, not zero.",
				"Native per-effect ReservedBase may include its rounded percent amount; do not sum it with ReservedPercent or reconstruct actor totals.",
				"Actor totals include global reservations and native rounding; effect rows are not an additive replacement.",
				"Modifier values are native skillModList totals before formula clamps and rounding; the ledger does not reapply those formulas.",
				"Runtime groups are not merged by name or effect ID; original-source merge history is not observed.",
				"No per-use or per-second costs, combat uptime, or real-character legality are certified.",
			},
		}
		for _, pool in ipairs(pools) do
			result.totals[pool] = {
				maximum = numberOrNull(actor.output[pool]),
				reservedCapped = numberOrNull(actor.output[pool .. "Reserved"]),
				unreserved = numberOrNull(actor.output[pool .. "Unreserved"]),
				nativeReservedFlatTotal = numberOrNull(actor["reserved_" .. pool .. "Base"]),
				nativeReservedPercentTotal = numberOrNull(actor["reserved_" .. pool .. "Percent"]),
			}
		end
		local groupIndices, gemIndices = {}, {}
		local actorSets = { [actor] = env.weaponSet }
		for weaponSet, otherEnv in pairs(env.weaponSetEnvs or {}) do
			if otherEnv.player then actorSets[otherEnv.player] = weaponSet end
		end
		for index, group in ipairs(build.skillsTab.socketGroupList or {}) do
			groupIndices[group] = index
			local indices = {}
			for gemIndex, gem in ipairs(group.gemList or {}) do indices[gem] = gemIndex end
			gemIndices[group] = indices
			result.groups[#result.groups + 1] = {
				groupIndex = index,
				skillSetId = valueOrNull(build.skillsTab.activeSkillSetId),
				enabled = group.enabled ~= false,
				set1Enabled = group.set1 ~= false, set2Enabled = group.set2 ~= false,
				usingWeaponSet = numberOrNull(group.usingSkillSet),
				sourceKind = group.sourceItem and "item" or group.sourceNode and "tree" or group.source and "other" or "ordinary",
				ownerSlot = group.slot and build.itemsTab.slots[group.slot] and group.slot or json.null,
				sourceItemId = numberOrNull(group.sourceItem and group.sourceItem.id),
				sourceNodeId = numberOrNull(group.sourceNode and group.sourceNode.id),
			}
		end
		for ordinal, skill in ipairs(actor.activeSkillList) do
			local effect = skill.activeEffect or {}
			local ge = effect.grantedEffect or {}
			local instance = effect.srcInstance
			local group = skill.socketGroup
			local groupIndex = group and groupIndices[group]
			local gemIndex = group and gemIndices[group] and gemIndices[group][instance]
			local sourceEffect = instance and ((instance.gemData and instance.gemData.grantedEffect) or instance.grantedEffect)
			local data = skill.skillData or {}
			local level = effect.grantedEffectLevel or {}
			local modList, cfg = skill.skillModList, skill.skillCfg
			local actorMatches = skill.actor == actor
			local reservesAll = data.reservesInAllWeaponSets and true or false
			local types = skill.skillTypes or {}
			local eligibleType = ((types[SkillType.HasReservation] or data.SupportedByAutoexertion)
				and not types[SkillType.ReservationBecomesCost])
				or (types[SkillType.SummonsTotem] and actor.modDB:Flag(nil, "AncestralBond"))
			local row = {
				effectOrdinal = ordinal, effectId = valueOrNull(ge.id),
				groupIndex = numberOrNull(groupIndex), gemIndex = numberOrNull(gemIndex),
				identityStatus = groupIndex and gemIndex and "bound" or "unmapped",
				sourceEffectId = valueOrNull(sourceEffect and sourceEffect.id),
				gemId = valueOrNull(instance and (instance.gemId or instance.gemData and instance.gemData.id)),
				gameGemId = valueOrNull(instance and instance.gemData and instance.gemData.gameId),
				actorMatches = actorMatches, actorWeaponSet = numberOrNull(actorSets[skill.actor]),
				reservesInAllWeaponSets = reservesAll,
				participatesInCurrentReservation = (actorMatches or reservesAll) and eligibleType and true or false,
				noReservation = instance and instance.noReservation and true or false,
				noSpiritReservation = instance and instance.noSpiritReservation and true or false,
				fromItem = instance and instance.fromItem and true or false,
				fromTree = instance and instance.fromTree and true or false,
				pools = {},
				reservationMultiplier = numberOrNull(modList and modList:More(cfg, "ReservationMultiplier")),
				extraSpirit = numberOrNull(modList and modList:Sum("BASE", cfg, "ExtraSpirit")),
				lifeReservePercentPerSpirit = numberOrNull(modList and modList:Sum("BASE", cfg, "LifeReservePercentPerSpirit")),
				bloodMagicReserved = modList and modList:Flag(cfg, "BloodMagicReserved") and true or false,
			}
			for _, pool in ipairs(pools) do
				local lower = pool:lower()
				row.pools[pool] = {
					nativeReservedBase = numberOrNull(data[pool .. "ReservedBase"]),
					nativeReservedPercent = numberOrNull(data[pool .. "ReservedPercent"]),
					grantedLevelFlat = numberOrNull(level[lower .. "ReservationFlat"]),
					grantedLevelPercent = numberOrNull(level[lower .. "ReservationPercent"]),
					skillDataFlat = numberOrNull(data[lower .. "ReservationFlat"]),
					skillDataPercent = numberOrNull(data[lower .. "ReservationPercent"]),
					forcedFlat = numberOrNull(data[pool .. "ReservationFlatForced"]),
					forcedPercent = numberOrNull(data[pool .. "ReservationPercentForced"]),
					efficiencyInc = numberOrNull(modList and modList:Sum("INC", cfg, pool .. "ReservationEfficiency", "ReservationEfficiency")),
					efficiencyMore = numberOrNull(modList and modList:More(cfg, pool .. "ReservationEfficiency", "ReservationEfficiency")),
					reservedInc = numberOrNull(modList and modList:Sum("INC", cfg, pool .. "Reserved", "Reserved")),
					reservedMore = numberOrNull(modList and modList:More(cfg, pool .. "Reserved", "Reserved")),
				}
			end
			result.effects[#result.effects + 1] = row
		end
		return result
	end
end

local RATE_DEPENDENT_SUPPORT_OBJECTIVES = {
	TotalDPS = true,
	FullDPS = true,
	CombinedDPS = true,
	Speed = true,
	MinionCombinedDPS = true,
	MinionTotalDPS = true,
}

local OFFENSIVE_SUPPORT_OBJECTIVES = {
	TotalDPS = true, FullDPS = true, CombinedDPS = true, AverageDamage = true,
	Speed = true, HitChance = true, CritChance = true, CritMultiplier = true,
	MinionCombinedDPS = true, MinionTotalDPS = true,
}

-- Internal support-optimizer preflight for one exact group/active effect. This reports runtime
-- facts only; Python owns the audit and delivery policy.
function methods.inspect_support_evaluation_capability(p)
	p = p or {}
	local index = math.floor(tonumber(p.index) or 0)
	local activeIndex = math.floor(tonumber(p.activeIndex) or 0)
	local group = (build.skillsTab.socketGroupList or {})[index]
	local active = group and group.displaySkillList and group.displaySkillList[activeIndex]
	if not group or not active then
		return {
			ok = false,
			errorCode = "support_capability_target_missing",
			capabilitySource = "pob_runtime",
		}
	end
	if (build.mainSocketGroup or 1) ~= index
		or (group.mainActiveSkillCalcs or group.mainActiveSkill or 1) ~= activeIndex then
		return {
			ok = false,
			errorCode = "support_capability_target_not_selected",
			capabilitySource = "pob_runtime",
		}
	end

	local reasons = {}
	local application = supportApplicationForGroup(group)
	local supportCount = math.max(0, #(group.gemList or {}) - 1)
	local applicationCheck = "verified"
	if group.noSupports or (group.gemList and group.gemList[1] and group.gemList[1].noSupports) then
		applicationCheck = "not_applicable"
	elseif supportCount > 0 then
		for _, applied in ipairs(application) do
			-- A support may serve the meta host or a reachable payload in this same group.
			-- Its own grant or an unanchored grant cycle cannot authorize its application;
			-- numerical capability below still belongs to the exact selected effect.
			if #(applied.activeSkills or {}) == 0 then applicationCheck = "failed" end
		end
	end
	if applicationCheck == "failed" then reasons[#reasons + 1] = "current_support_not_applied" end

	local ge = active.activeEffect and active.activeEffect.grantedEffect
	-- A support may change when an effect is usable without PoB modelling the time spent
	-- satisfying that condition. Preserve this mechanical contract during numeric searches.
	-- Bind applied support/effect identities, not display names or a hand-maintained gem list.
	local usageConditionContracts = {}
	for _, candidate in ipairs(group.displaySkillList or {}) do
		local candidateGe = candidate.activeEffect and candidate.activeEffect.grantedEffect
		for _, effect in ipairs(candidate.supportList or {}) do
			local supportGe = effect.grantedEffect
			local applied = candidateGe and effect.supportedActiveEffectIds
				and effect.supportedActiveEffectIds[candidateGe.id]
			if applied and supportGe then
				for _, kind in ipairs(supportGe.addSkillTypes or {}) do
					if kind == SkillType.HasUsageCondition then
						usageConditionContracts[#usageConditionContracts + 1] = {
							effectId = candidateGe.id,
							supportEffectId = supportGe.id,
						}
						break
					end
				end
			end
		end
	end
	local selectedTriggered = hasType(ge, "Triggered") or hasType(ge, "InbuiltTrigger")
		or (active.skillData and active.skillData.triggered) and true or false
	local hasMetaHost = false
	local hasProxyHost = false
	local rateSourceEffectIds = {}
	for _, candidate in ipairs(group.displaySkillList or {}) do
		local candidateGe = candidate.activeEffect and candidate.activeEffect.grantedEffect
		if hasType(candidateGe, "Meta") and hasType(candidateGe, "Triggers") then
			hasMetaHost = true
			rateSourceEffectIds[#rateSourceEffectIds + 1] = candidateGe.id
		end
		-- Native proxy-spawn effects need their own creation cadence. The payload's bow
		-- attack Speed does not model the spawn cooldown, lifetime, or active proxy count.
		if hasType(candidateGe, "UsedByProxy") and hasType(candidateGe, "Cooldown")
			and hasType(candidateGe, "Duration") and hasType(candidateGe, "Buff") then
			hasProxyHost = true
			rateSourceEffectIds[#rateSourceEffectIds + 1] = candidateGe.id
		end
	end
	local rateDependent = false
	local offensiveObjective = false
	for _, key in ipairs(p.objectiveKeys or {}) do
		if RATE_DEPENDENT_SUPPORT_OBJECTIVES[tostring(key)] then rateDependent = true end
		if OFFENSIVE_SUPPORT_OBJECTIVES[tostring(key)] then offensiveObjective = true end
	end

	local triggerRate = "not_applicable"
	local numericRanking = applicationCheck == "failed" and "unsupported" or "supported"
	local output = (build.calcsTab and build.calcsTab.mainOutput) or {}
	local declaredDamageModel = "not_flagged_incomplete"
	-- A duration-based destructible DoT object may expose only its weapon-impact calculation
	-- while the object model is absent. That partial hit readout does not certify the missing
	-- model or a whole support-set upgrade. This is broader than a rate-only gap and stays blocked.
	if offensiveObjective and hasType(ge, "ObjectDurability")
		and hasType(ge, "DamageOverTime") and hasType(ge, "Duration")
		and asOptionalNumber(output.Duration) == nil
		and asOptionalNumber(output.DurationSecondary) == nil
		and asOptionalNumber(output.DurationTertiary) == nil
		and (asOptionalNumber(output.TotalDot) or 0) <= 0 then
		declaredDamageModel = "incomplete"
		numericRanking = "unsupported"
		reasons[#reasons + 1] = "declared_duration_dot_model_missing"
	end
	if rateDependent and (selectedTriggered or hasMetaHost or hasProxyHost or hasType(ge, "Herald")) then
		local candidates = {}
		local function addRate(value)
			value = asOptionalNumber(value)
			if value ~= nil then candidates[#candidates + 1] = value end
		end
		addRate(output.SkillTriggerRate)
		addRate(active.skillData and active.skillData.triggerRate)
		if active.skillData and asOptionalNumber(active.skillData.triggerTime) ~= nil
			and asOptionalNumber(output.Speed) ~= nil then
			addRate(output.Speed)
		end
		local rateSeen = false
		local positiveRate = false
		for _, value in ipairs(candidates) do
			if value ~= nil then
				rateSeen = true
				if value > 0 then positiveRate = true end
			end
		end
		if positiveRate then
			triggerRate = "modelled"
		elseif rateSeen then
			triggerRate = "zero_or_inactive"
			numericRanking = "unsupported"
			reasons[#reasons + 1] = "trigger_rate_zero_or_inactive"
		else
			triggerRate = "unmodelled"
			numericRanking = "unsupported"
			reasons[#reasons + 1] = "trigger_rate_unmodelled"
		end
	end
	local function selectedHasType(name)
		local kind = type(SkillType) == "table" and SkillType[name]
		return hasType(ge, name) or (kind and active.skillTypes and active.skillTypes[kind] and true) or false
	end
	local minionActor = selectedHasType("Minion")
	local playerDamageRole = selectedHasType("Attack") or selectedHasType("Damage")
		or selectedHasType("Projectile") or selectedHasType("DamageOverTime")
	return {
		ok = true,
		applicationCheck = applicationCheck,
		selectedEffectId = ge and ge.id,
		numericRanking = numericRanking,
		triggerRate = triggerRate,
		reasonCodes = reasons,
		capabilitySource = "pob_runtime",
		supportApplication = application,
		declaredDamageModel = declaredDamageModel,
		rateSourceEffectIds = rateSourceEffectIds,
		usageConditionContractVersion = 1,
		usageConditionContracts = usageConditionContracts,
		objectiveContext = {
			version = 1,
			selectedEffectId = ge and ge.id,
			actor = minionActor and (playerDamageRole and "mixed" or "minion") or "player",
			roles = {
				duration = selectedHasType("Duration"),
				area = selectedHasType("Area"),
				curse = selectedHasType("Curse") or selectedHasType("AppliesCurse"),
			},
		},
	}
end

-- Read-only support identity lookup. Corpus IDs bind the runtime identity. A separate exact
-- runtime-name discovery path lets Python verify canonical labels against corpus IDs afterwards.
function methods.resolve_support_gem_identity(p)
	p = p or {}
	local gemIds, effectIds = {}, {}
	for _, id in ipairs(p.gemIds or {}) do gemIds[tostring(id)] = true end
	for _, id in ipairs(p.effectIds or {}) do effectIds[tostring(id)] = true end
	local nameOnly = next(gemIds) == nil and next(effectIds) == nil
	local runtimeName = type(p.runtimeName) == "string" and p.runtimeName or ""
	if nameOnly and runtimeName == "" then
		return { ok = false, errorCode = "support_identity_required" }
	end
	local matches = {}
	for id, gem in pairs((build.data and build.data.gems) or {}) do
		local effect = gem.grantedEffect
		if effect and effect.support then
			local effectId = gem.grantedEffectId or effect.id
			if gemIds[tostring(id)] or gemIds[tostring(gem.gameId)]
				or effectIds[tostring(effectId)] or (nameOnly and gem.name == runtimeName) then
				matches[#matches + 1] = {
					name = gem.name,
					gemId = tostring(id),
					gameId = gem.gameId,
					effectId = effectId,
					naturalMaxLevel = gem.naturalMaxLevel,
				}
			end
		end
	end
	if #matches == 0 then return { ok = true, status = "model_unavailable" } end
	if #matches > 1 then
		table.sort(matches, function(a, b) return a.gemId < b.gemId end)
		return { ok = true, status = "ambiguous", candidates = matches }
	end
	local result = matches[1]
	result.ok = true
	result.status = "resolved"
	return result
end

function methods.configure_source_skill_supports(p)
	p = p or {}
	local index = math.floor(tonumber(p.index) or 0)
	local list = build.skillsTab.socketGroupList or {}
	local group = list[index]
	if not group then
		return { ok = false, errorCode = "skill_group_not_found", error = "skill group not found" }
	end
	local source = type(group.source) == "string" and group.source or ""
	local isTreeSource = group.sourceNode ~= nil and source:match("^Tree:") ~= nil
	local isItemSource = group.sourceItem ~= nil and source:match("^Item:") ~= nil
	local isDefaultAttack = defaultAttackLevelForSocketGroup(group) ~= nil
	if not isTreeSource and not isItemSource and not isDefaultAttack then
		return {
			ok = false,
			errorCode = "configurable_source_skill_group_required",
			error = "only real passive, ascendancy, item, or native default attack groups can be configured",
		}
	end
	local root = group.gemList and group.gemList[1]
	if not root then
		return { ok = false, errorCode = "source_skill_root_missing", error = "source skill root is missing" }
	end
	if group.noSupports or root.noSupports then
		return { ok = false, errorCode = "source_skill_no_supports", error = "source skill does not accept supports" }
	end

	local supportIds = p.supportGemIds or {}
	local payloads = {}
	for gemIndex = 2, #(group.gemList or {}) do
		local gem = group.gemList[gemIndex]
		local effect = (gem.gemData and gem.gemData.grantedEffect) or gem.grantedEffect
		if not effect or not effect.support then
			payloads[#payloads + 1] = gem
		end
	end
	local capacity = math.max(0, sourceSupportCapacity(root.level) - #payloads)
	if #supportIds > capacity then
		return {
			ok = false,
			errorCode = "source_support_capacity_exceeded",
			error = "requested supports exceed the source skill capacity",
			capacity = capacity,
		}
	end
	local supports = {}
	local seenIds, seenFamilies = {}, {}
	for _, supportId in ipairs(supportIds) do
		local gemData = build.data and build.data.gems and build.data.gems[tostring(supportId)]
		if not gemData and build.data and build.data.gemsByGameId then
			local variants = build.data.gemsByGameId[tostring(supportId)]
			if variants then
				for _, variant in pairs(variants) do
					gemData = variant
					break
				end
			end
		end
		if not gemData or not gemData.grantedEffect or not gemData.grantedEffect.support then
			return { ok = false, errorCode = "invalid_support_gem", error = "unknown or non-support gem", supportGemId = supportId }
		end
		local family = gemData.gemFamily or gemData.grantedEffect.id or gemData.id
		if seenIds[gemData.id] or seenFamilies[family] then
			return { ok = false, errorCode = "duplicate_support_family", error = "duplicate support or support family", supportGemId = supportId }
		end
		seenIds[gemData.id] = true
		seenFamilies[family] = true
		supports[#supports + 1] = gemData
	end

	local snapshot = build:SaveDB("code")
	local beforeSource = group.source
	local beforeSkillId = root.skillId
	local beforeLevel = asNumber(root.level)
	local beforeMainActive = group.mainActiveSkill or 1
	local beforeMainActiveCalcs = group.mainActiveSkillCalcs or beforeMainActive
	local function effectIdAt(activeIndex)
		local active = group.displaySkillList and group.displaySkillList[activeIndex]
		return active and active.activeEffect and active.activeEffect.grantedEffect and active.activeEffect.grantedEffect.id
	end
	local beforeMainEffect = effectIdAt(beforeMainActive)
	local beforeCalcsEffect = effectIdAt(beforeMainActiveCalcs)
	local beforeEnabled = group.enabled ~= false
	local beforeLabel = group.label or ""
	local beforeFullDPS = group.includeInFullDPS and true or false
	local beforeGroupCount = #list
	local beforeSourceCount = 0
	for _, candidate in ipairs(list) do
		if candidate.source ~= nil then beforeSourceCount = beforeSourceCount + 1 end
	end
	local beforeSpirit = spiritState()
	local function rollback(code, message, extra)
		loadBuildFromXML(snapshot)
		runCallback("OnFrame")
		local result = { ok = false, errorCode = code, error = message }
		for key, value in pairs(extra or {}) do result[key] = value end
		return result
	end

	wipeTable(group.gemList)
	table.insert(group.gemList, root)
	for _, payload in ipairs(payloads) do
		table.insert(group.gemList, payload)
	end
	for _, gemData in ipairs(supports) do
		table.insert(group.gemList, {
			gemId = gemData.id,
			skillId = gemData.grantedEffectId,
			nameSpec = gemData.name,
			level = gemData.naturalMaxLevel or 1,
			quality = 20,
			enabled = true,
			enableGlobal1 = true,
			count = 1,
		})
	end
	build.skillsTab:ProcessSocketGroup(group)
	build.buildFlag = true
	build.modFlag = true
	runCallback("OnFrame")

	group = (build.skillsTab.socketGroupList or {})[index]
	root = group and group.gemList and group.gemList[1]
	if not group or group.source ~= beforeSource or not root or root.skillId ~= beforeSkillId then
		return rollback("source_skill_identity_changed", "source or root skill changed during support configuration")
	end
	if asNumber(root.level) ~= beforeLevel
		or (isTreeSource and asNumber(build.characterLevel) >= 95 and asNumber(root.level) ~= 20) then
		return rollback("source_skill_level_changed", "source skill level changed during support configuration", { skillLevel = root.level })
	end
	if #build.skillsTab.socketGroupList ~= beforeGroupCount then
		return rollback("source_group_count_changed", "skill group count changed during support configuration")
	end
	local afterSourceCount = 0
	for _, candidate in ipairs(build.skillsTab.socketGroupList) do
		if candidate.source ~= nil then afterSourceCount = afterSourceCount + 1 end
	end
	if afterSourceCount > beforeSourceCount then
		return rollback("source_group_count_increased", "source skill group count increased during support configuration")
	end
	if (group.mainActiveSkill or 1) ~= beforeMainActive
		or (group.mainActiveSkillCalcs or group.mainActiveSkill or 1) ~= beforeMainActiveCalcs
		or effectIdAt(beforeMainActive) ~= beforeMainEffect
		or effectIdAt(beforeMainActiveCalcs) ~= beforeCalcsEffect
		or (group.enabled ~= false) ~= beforeEnabled
		or (group.label or "") ~= beforeLabel
		or (group.includeInFullDPS and true or false) ~= beforeFullDPS then
		return rollback("source_group_state_changed", "source group state or Command selection changed during support configuration")
	end
	if #(group.gemList or {}) ~= #supports + #payloads + 1 then
		return rollback("source_supports_not_preserved", "not all requested supports survived source group refresh")
	end
	for payloadIndex, payload in ipairs(payloads) do
		if group.gemList[payloadIndex + 1] ~= payload then
			return rollback("source_payloads_not_preserved", "an active payload changed during support configuration")
		end
	end
	for supportIndex, gemData in ipairs(supports) do
		local actual = group.gemList[supportIndex + #payloads + 1]
		if not actual or actual.gemId ~= gemData.id then
			return rollback("source_supports_not_preserved", "requested supports did not survive in order", { supportIndex = supportIndex })
		end
	end

	local application = supportApplicationForGroup(group)
	local selectedName = skillNameAt(index, beforeMainActiveCalcs)
	local selectedSupported = #supports == 0
	for supportIndex, applied in ipairs(application) do
		if #applied.activeSkills == 0 then
			return rollback("source_support_not_applied", "a support does not affect any active effect", { supportIndex = supportIndex, support = applied.name, supportApplication = application })
		end
		for _, activeName in ipairs(applied.activeSkills) do
			if activeName == selectedName then selectedSupported = true end
		end
	end
	if not selectedSupported then
		return rollback("source_command_unsupported", "no requested support affects the selected Command", { selectedCommand = selectedName })
	end

	local afterSpirit = spiritState()
	if afterSpirit.overBy and afterSpirit.overBy > 0 then
		return rollback("spirit_over_reserved", "support configuration over-reserves Spirit", { spirit = afterSpirit })
	end
	build.buildFlag = true
	build.modFlag = true
	runCallback("OnFrame")
	local steadySpirit = spiritState()
	if asNumber(afterSpirit.requested) ~= asNumber(steadySpirit.requested)
		or asNumber(afterSpirit.reserved) ~= asNumber(steadySpirit.reserved) then
		return rollback("spirit_reservation_unstable", "Spirit reservation changed across repeated calculation frames")
	end
	group = build.skillsTab.socketGroupList[index]
	root = group and group.gemList and group.gemList[1]
	if not group or group.source ~= beforeSource or not root or root.skillId ~= beforeSkillId
		or asNumber(root.level) ~= beforeLevel or #(group.gemList or {}) ~= #supports + #payloads + 1
		or (group.mainActiveSkill or 1) ~= beforeMainActive
		or (group.mainActiveSkillCalcs or group.mainActiveSkill or 1) ~= beforeMainActiveCalcs
		or effectIdAt(beforeMainActive) ~= beforeMainEffect
		or effectIdAt(beforeMainActiveCalcs) ~= beforeCalcsEffect
		or (group.enabled ~= false) ~= beforeEnabled
		or (group.label or "") ~= beforeLabel
		or (group.includeInFullDPS and true or false) ~= beforeFullDPS then
		return rollback("source_group_unstable", "source group identity or Command selection changed on a repeated frame")
	end
	for payloadIndex, payload in ipairs(payloads) do
		if group.gemList[payloadIndex + 1] ~= payload then
			return rollback("source_payloads_unstable", "an active payload changed on a repeated frame")
		end
	end
	for supportIndex, gemData in ipairs(supports) do
		local actual = group.gemList[supportIndex + #payloads + 1]
		if not actual or actual.gemId ~= gemData.id then
			return rollback("source_supports_unstable", "a requested support changed on a repeated frame", { supportIndex = supportIndex })
		end
	end
	application = supportApplicationForGroup(group)
	selectedSupported = #supports == 0
	for supportIndex, applied in ipairs(application) do
		if #applied.activeSkills == 0 then
			return rollback("source_support_not_applied", "a support stopped affecting active effects on a repeated frame", { supportIndex = supportIndex, support = applied.name })
		end
		for _, activeName in ipairs(applied.activeSkills) do
			if activeName == selectedName then selectedSupported = true end
		end
	end
	if not selectedSupported then
		return rollback("source_command_unsupported", "the selected Command lost all requested support effects on a repeated frame", { selectedCommand = selectedName })
	end

	return {
		ok = true,
		state = skillGroupState(),
		source = beforeSource,
		skillLevel = beforeLevel,
		capacity = capacity,
		selectedCommand = selectedName,
		supportApplication = application,
		spiritBefore = beforeSpirit,
		spiritAfter = steadySpirit,
	}
end

-- One source probe after Python reloads the immutable full snapshot. Keep the existing native
-- source mutation/stability checks, but avoid repeating selection and serializing all groups
-- for separate capability/stat RPCs. This does not introduce a group-local source mutation path.
function methods.probe_source_skill_group(p)
	p = p or {}
	local index = math.floor(tonumber(p.index) or 0)
	local activeIndex = math.floor(tonumber(p.activeSkillIndex) or 0)
	local group = (build.skillsTab.socketGroupList or {})[index]
	if not group or not group.source or group.source ~= p.expectedSource then
		return { ok = false, errorCode = "source_skill_identity_changed" }
	end
	if activeIndex < 1 or type(p.expectedSkillName) ~= "string" or p.expectedSkillName == "" then
		return { ok = false, errorCode = "support_probe_target_required" }
	end
	-- Selecting first activates inactive weapon/item sources. The exact effect is checked after
	-- that calculation, before any supports are configured; no guessed display-name substitution.
	selectMainSocketGroup(index, activeIndex)
	group = (build.skillsTab.socketGroupList or {})[index]
	local active = group and group.displaySkillList and group.displaySkillList[activeIndex]
	local effect = active and active.activeEffect and active.activeEffect.grantedEffect
	if not group or group.source ~= p.expectedSource or skillNameAt(index, activeIndex) ~= p.expectedSkillName
		or (p.expectedEffectId and (not effect or effect.id ~= p.expectedEffectId)) then
		return { ok = false, errorCode = "support_selected_effect_changed" }
	end
	local configured = methods.configure_source_skill_supports({ index = index, supportGemIds = p.supportGemIds })
	if not configured.ok then return configured end
	group = (build.skillsTab.socketGroupList or {})[index]
	local matches = 0
	for candidateIndex, candidate in ipairs(group and group.displaySkillList or {}) do
		local candidateEffect = candidate.activeEffect and candidate.activeEffect.grantedEffect
		if skillNameAt(index, candidateIndex) == p.expectedSkillName
			and (not p.expectedEffectId or (candidateEffect and candidateEffect.id == p.expectedEffectId)) then
			matches = matches + 1
		end
	end
	if matches ~= 1 then
		return { ok = false, errorCode = matches > 1 and "support_selected_effect_ambiguous" or "support_selected_effect_changed" }
	end
	return {
		ok = true,
		activeSkillIndex = activeIndex,
		state = configured.state,
		capability = methods.inspect_support_evaluation_capability({
			index = index, activeIndex = activeIndex, objectiveKeys = p.objectiveKeys or {},
		}),
		stats = collectStats(p.keys),
	}
end

-- Replace exactly one user-owned group while preserving its position and group-level state.  The
-- Python layer guards the index with a content fingerprint; this low-level method snapshots again
-- so parse/legality failures never leave a partial group behind.
-- Internal support-search probe. LoadSkill is PoB's own complete Gem/settings reader; only
-- the requested ordinary group is rebuilt. Tree/items/config stay live between probes.
-- Python owns the enclosing read-only transaction and restores the original complete build.
-- activeSkillIndex seeds the first frame; the exact effect ID/name uniquely selects the final
-- output because support-granted effects may move its index. Topology changes return no stats
-- and require the caller to rebuild the candidate from its immutable complete snapshot.
function methods.probe_regular_skill_group(p)
	p = p or {}
	local index = math.floor(tonumber(p.index) or 0)
	local activeIndex = math.floor(tonumber(p.activeSkillIndex) or 0)
	local tab = build.skillsTab
	local list = tab.socketGroupList or {}
	local previous = list[index]
	if not previous or previous.source ~= nil then
		return { ok = false, errorCode = "ordinary_skill_group_required" }
	end
	if activeIndex < 1 or type(p.expectedSkillName) ~= "string" or p.expectedSkillName == "" then
		return { ok = false, errorCode = "support_probe_target_required" }
	end
	local parsed, parseError = common.xml.ParseXML(tostring(p.groupXml or ""))
	local node = parsed and parsed[1]
	if parseError or not node or node.elem ~= "Skill" or #parsed ~= 1
		or (node.attrib.source and node.attrib.source ~= "") then
		return { ok = false, errorCode = "support_probe_group_xml_invalid" }
	end
	-- Exact runtime variant IDs returned by resolve_support_gem_identity must not fall
	-- through LoadSkill's legacy name search. Existing saved gameId/variantId pairs retain
	-- their original meaning; new runtime IDs are converted to that native save format.
	for _, gemNode in ipairs(node) do
		if gemNode.elem ~= "Gem" then
			return { ok = false, errorCode = "support_probe_group_xml_invalid" }
		end
		local direct = gemNode.attrib.gemId and build.data.gems[gemNode.attrib.gemId]
		if direct then
			gemNode.attrib.gemId = direct.gameId or gemNode.attrib.gemId
			gemNode.attrib.variantId = direct.variantId
		end
	end
	local beforeCount = #list
	local beforeGroups = {}
	for position, group in ipairs(list) do beforeGroups[position] = group end
	local beforeSkills = { elem = "Skills" }
	tab:Save(beforeSkills)
	local function activeNodes(skills)
		for _, child in ipairs(skills) do
			if child.elem == "SkillSet" and tonumber(child.attrib.id) == tab.activeSkillSetId then return child end
		end
		return {}
	end
	local function sameNode(a, b)
		if type(a) ~= "table" or type(b) ~= "table" then return a == b end
		if a.elem ~= b.elem or #a ~= #b then return false end
		for key, value in pairs(a.attrib or {}) do if (b.attrib or {})[key] ~= value then return false end end
		for key, value in pairs(b.attrib or {}) do if (a.attrib or {})[key] ~= value then return false end end
		for position, child in ipairs(a) do if not sameNode(child, b[position]) then return false end end
		return true
	end
	local snapshot = build:SaveDB("code")
	local function rollback(code, message)
		local restored = pcall(function()
			loadBuildFromXML(snapshot)
			runCallback("OnFrame")
		end)
		return { ok = false, errorCode = code, error = message, rolledBack = restored,
			recoveryRequired = not restored }
	end
	local ok, result = pcall(function()
		tab:LoadSkill(node, tab.activeSkillSetId)
		if #list ~= beforeCount + 1 then
			error("support probe must load exactly one socket group")
		end
		local replacement = table.remove(list, #list)
		list[index] = replacement
		if tab.displayGroup == previous then tab:SetDisplayGroup(replacement) end
		selectMainSocketGroup(index, activeIndex)
		local afterSkills = { elem = "Skills" }
		tab:Save(afterSkills)
		local beforeNodes, afterNodes = activeNodes(beforeSkills), activeNodes(afterSkills)
		local requiresRebuild = #tab.socketGroupList ~= beforeCount
		for position, group in ipairs(beforeGroups) do
			if position ~= index and (tab.socketGroupList[position] ~= group
				or not sameNode(beforeNodes[position], afterNodes[position])) then requiresRebuild = true end
		end
		if requiresRebuild then
			-- No conclusion is returned from changed topology. The enclosing Python transaction
			-- rebuilds this candidate from its immutable complete snapshot using PoB's full loader.
			return { ok = true, requiresFullRebuild = true, reasonCode = "support_probe_topology_changed" }
		end
		local selected = tab.socketGroupList[index]
		local matchedIndex
		for candidateIndex, candidate in ipairs(selected and selected.displaySkillList or {}) do
			local effect = candidate.activeEffect and candidate.activeEffect.grantedEffect
			if skillNameAt(index, candidateIndex) == p.expectedSkillName
				and (not p.expectedEffectId or (effect and effect.id == p.expectedEffectId)) then
				if matchedIndex then return rollback("support_selected_effect_ambiguous") end
				matchedIndex = candidateIndex
			end
		end
		if not selected or selected.source ~= nil or not matchedIndex then
			return rollback("support_selected_effect_changed")
		end
		if (selected.mainActiveSkillCalcs or selected.mainActiveSkill) ~= matchedIndex then
			selectMainSocketGroup(index, matchedIndex)
		end
		return {
			ok = true,
			activeSkillIndex = matchedIndex,
			state = skillGroupState(),
			capability = methods.inspect_support_evaluation_capability({
				index = index, activeIndex = matchedIndex, objectiveKeys = p.objectiveKeys or {},
			}),
			stats = collectStats(p.keys),
		}
	end)
	if not ok then return rollback("support_probe_failed", tostring(result)) end
	return result
end

function methods.replace_skill_group(p)
	p = p or {}
	local index = math.floor(tonumber(p.index) or 0)
	local list = build.skillsTab.socketGroupList or {}
	local previous = list[index]
	if not previous then
		return { ok = false, errorCode = "skill_group_not_found", error = "skill group not found" }
	end
	if previous.source ~= nil then
		return {
			ok = false,
			errorCode = "source_skill_group_immutable",
			error = "item/passive-provided skill groups cannot be replaced directly",
		}
	end
	if not p.text or tostring(p.text) == "" then
		return { ok = false, errorCode = "skill_text_required", error = "replacement skill text is required" }
	end

	local snapshot = build:SaveDB("code")
	local before = #list
	local previousMain = build.mainSocketGroup or 1
	local previousMainActive = list[previousMain] and list[previousMain].mainActiveSkill or 1
	pasteSocketGroup(p.text)
	if #list ~= before + 1 then
		loadBuildFromXML(snapshot)
		runCallback("OnFrame")
		return {
			ok = false,
			errorCode = "skill_group_parse_failed",
			error = "replacement must parse into exactly one skill group; build left unchanged",
		}
	end

	local replacement = list[#list]
	table.remove(list, #list)
	replacement.label = previous.label
	replacement.slot = previous.slot
	replacement.enabled = previous.enabled
	replacement.includeInFullDPS = previous.includeInFullDPS
	replacement.groupCount = previous.groupCount
	list[index] = replacement
	build.skillsTab:ProcessSocketGroup(replacement)
	local replacementGems = gemSummaryForSocketGroup(index)
	local activeCount = 0
	for _, gem in ipairs(replacementGems) do
		if gem.isActive then activeCount = activeCount + 1 end
	end
	if activeCount == 0 then
		loadBuildFromXML(snapshot)
		runCallback("OnFrame")
		return {
			ok = false,
			errorCode = "skill_group_has_no_active_skill",
			error = "replacement group has no recognized active skill; build left unchanged",
		}
	end
	local levelViolations = activeGemLevelViolationsForSocketGroup(index)
	if #levelViolations > 0 and asNumber(build.characterLevel) > 1 then
		loadBuildFromXML(snapshot)
		runCallback("OnFrame")
		return {
			ok = false,
			errorCode = "active_skill_gem_level_requirement_unmet",
			error = "an active gem level exceeds the current character-level requirement",
			violations = levelViolations,
		}
	end

	local activeIndex = math.floor(tonumber(p.activeSkillIndex) or previous.mainActiveSkill or 1)
	if activeIndex < 1 or not replacement.displaySkillList or not replacement.displaySkillList[activeIndex] then
		activeIndex = 1
	end
	replacement.mainActiveSkill = activeIndex
	replacement.mainActiveSkillCalcs = activeIndex
	if previousMain == index then
		selectMainSocketGroup(index, activeIndex)
	else
		selectMainSocketGroup(previousMain, previousMainActive)
	end
	if build.skillsTab.controls and build.skillsTab.controls.groupList then
		local control = build.skillsTab.controls.groupList
		control.selIndex = build.mainSocketGroup
		control.selValue = list[build.mainSocketGroup]
	end
	return { ok = true, state = skillGroupState() }
end

function methods.remove_skill_group(p)
	p = p or {}
	local index = math.floor(tonumber(p.index) or 0)
	local list = build.skillsTab.socketGroupList or {}
	local group = list[index]
	if not group then
		return { ok = false, errorCode = "skill_group_not_found", error = "skill group not found" }
	end
	if group.source ~= nil then
		return {
			ok = false,
			errorCode = "source_skill_group_immutable",
			error = "item/passive-provided skill groups cannot be removed directly",
		}
	end
	if #list <= 1 then
		return {
			ok = false,
			errorCode = "cannot_remove_only_skill_group",
			error = "the only skill group cannot be removed; replace it instead",
		}
	end

	local mainIndex = build.mainSocketGroup or 1
	local replacementIndex = math.floor(tonumber(p.replacementMainGroupIndex) or 0)
	if mainIndex == index then
		if replacementIndex < 1 or replacementIndex > #list or replacementIndex == index then
			return {
				ok = false,
				errorCode = "replacement_main_group_required",
				error = "removing the main group requires another existing replacementMainGroupIndex",
			}
		end
		if list[replacementIndex].enabled == false then
			return {
				ok = false,
				errorCode = "replacement_main_group_disabled",
				error = "replacementMainGroupIndex must identify an enabled skill group",
			}
		end
		mainIndex = replacementIndex
	end

	table.remove(list, index)
	if mainIndex > index then mainIndex = mainIndex - 1 end
	if build.skillsTab.controls and build.skillsTab.controls.groupList then
		local control = build.skillsTab.controls.groupList
		control.selIndex = mainIndex
		control.selValue = list[mainIndex]
	end
	local activeIndex = list[mainIndex] and list[mainIndex].mainActiveSkill or 1
	selectMainSocketGroup(mainIndex, activeIndex)
	return { ok = true, state = skillGroupState() }
end

local function utf8Prefix(value, limit)
	local text, cursor, count = tostring(value), 1, 0
	while cursor <= #text and count < limit do
		local first = text:byte(cursor)
		local width = first < 128 and 1 or first >= 194 and first <= 223 and 2
			or first >= 224 and first <= 239 and 3 or first >= 240 and first <= 244 and 4 or nil
		if not width or cursor + width - 1 > #text then error("invalid_utf8_label") end
		local second = text:byte(cursor + 1)
		if (first == 224 and second < 160) or (first == 237 and second >= 160)
			or (first == 240 and second < 144) or (first == 244 and second > 143) then
			error("invalid_utf8_label")
		end
		for index = cursor + 1, cursor + width - 1 do
			local byte = text:byte(index)
			if byte < 128 or byte > 191 then error("invalid_utf8_label") end
		end
		cursor, count = cursor + width, count + 1
	end
	return text:sub(1, cursor - 1)
end

function methods.set_skill_group_state(p)
	p = p or {}
	local index = math.floor(tonumber(p.index) or 0)
	local list = build.skillsTab.socketGroupList or {}
	local group = list[index]
	if not group then
		return { ok = false, errorCode = "skill_group_not_found", error = "skill group not found" }
	end
	if index == (build.mainSocketGroup or 1) and p.enabled == false and not p.makeMain then
		return {
			ok = false,
			errorCode = "main_skill_group_cannot_be_disabled",
			error = "select another main group before disabling the current main group",
		}
	end
	if p.makeMain and (p.enabled == false or (p.enabled == nil and group.enabled == false)) then
		return {
			ok = false,
			errorCode = "disabled_group_cannot_be_main",
			error = "a group cannot be made main and disabled in the same mutation",
		}
	end
	local activeIndex = p.activeSkillIndex and math.floor(tonumber(p.activeSkillIndex) or 0) or nil
	if activeIndex and (activeIndex < 1 or not group.displaySkillList or not group.displaySkillList[activeIndex]) then
		return {
			ok = false,
			errorCode = "active_skill_index_invalid",
			error = "activeSkillIndex does not identify an active skill in this group",
		}
	end

	-- Validate before changing any flags so malformed Unicode cannot partially mutate a group.
	local label = p.label ~= nil and utf8Prefix(p.label, 50) or nil
	if p.enabled ~= nil then group.enabled = p.enabled and true or false end
	if p.includeInFullDPS ~= nil then group.includeInFullDPS = p.includeInFullDPS and true or false end
	if label ~= nil then group.label = label end
	if activeIndex then
		group.mainActiveSkill = activeIndex
		group.mainActiveSkillCalcs = activeIndex
	end
	if p.makeMain then
		selectMainSocketGroup(index, activeIndex or group.mainActiveSkill or 1)
	else
		build.buildFlag = true
		build.modFlag = true
		runCallback("OnFrame")
	end
	return { ok = true, state = skillGroupState() }
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

local function activeCustomMods()
	local config = build.configTab
	local configSet = config and config.configSets[config.activeConfigSetId]
	local parts = {}
	for _, block in ipairs(configSet and configSet.customModsList or {}) do
		if block.enabled ~= false and block.text and #block.text > 0 then
			parts[#parts + 1] = block.text
		end
	end
	if #parts > 0 then return table.concat(parts, "\n") end
	return config and config.input.customMods or ""
end

-- Set combat/config options (configTab.input keys) and/or raw custom mods, then recompute.
function methods.set_config(p)
	p = p or {}
	local opts = (type(p.options) == "table") and p.options or {}
	for k, v in pairs(opts) do
		if k ~= "customMods" then build.configTab.input[k] = v end
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
	local customMods = type(p.customMods) == "string" and p.customMods or opts.customMods
	if type(customMods) == "string" then
		-- Explicit custom_mods replaces that field in the active configuration.
		-- Write the native block format so Save/Load cannot migrate a stale Input
		-- or let pre-existing blocks silently override the requested replacement.
		local config = build.configTab
		config.configSets[config.activeConfigSetId].customModsList = {
			{ title = "Default", enabled = true, text = customMods },
		}
		config.input.customMods = nil
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
	-- The caller supplies the complete item, so do not use the UI paste path: it
	-- copies the currently equipped item's anoint/runes and populates slots before
	-- this replacement has been attached. Parse with PoB, then replace in one step.
	local ok, newItem = pcall(function() return new("Item"):Item(raw) end)
	if not ok then
		return false, "parse error: " .. tostring(newItem)
	end
	if not newItem or not newItem.base then
		return false, "item not created (unrecognized base type?)"
	end
	local sl = slot or newItem:GetPrimarySlot()
	local sc = build.itemsTab.slots[sl]
	if not sc then
		return false, "unknown slot: " .. tostring(sl)
	end
	local priorItem = build.itemsTab.items[sc.selItemId]
	local attached, err = pcall(function()
		build.itemsTab:AddItem(newItem, true) -- no auto-equip or intermediate PopulateSlots
		sc:SetSelItemId(newItem.id)
		-- Item IDs change on replacement. Carry a configured group only when its actual old
		-- owner, slot and unique native root effect still exist on the new item. PoB remains
		-- responsible for the grant's derived level/quality/requirements on the next frame.
		for _, group in ipairs(build.skillsTab.socketGroupList or {}) do
			local root = group.gemList and group.gemList[1]
			if priorItem and group.sourceItem == priorItem and group.slot == sl and root then
				local matches = {}
				for _, grant in ipairs(newItem.grantedSkills or {}) do
					if grant.skillId == root.skillId then matches[#matches + 1] = grant end
				end
				if #matches == 1 and (group.noSupports and true or false) == (matches[1].noSupports and true or false) then
					group.source, group.sourceItem = matches[1].source, newItem
				end
			end
		end
		-- Validate against the complete new loadout. A genuinely incompatible new
		-- weapon may invalidate its offhand; the caller's input/legality guard rejects it.
		build.itemsTab:PopulateSlots()
	end)
	if not attached then return false, "equip error: " .. tostring(err) end
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
		local mods, seen, constraints = {}, {}, {}
		for _, key in ipairs({ baseType, specificType }) do
			if key and not seen[key] and rdata[key] then
				seen[key] = true
				local option = rdata[key]
				if option.limit then
					constraints[#constraints + 1] = {
						group = option.limitId or name,
						limit = option.limit,
						evidencePatch = option.limitEvidencePatch,
						evidenceRef = option.limitEvidenceRef,
					}
				end
				for _, line in ipairs(rdata[key]) do
					mods[#mods + 1] = line
				end
			end
		end
		if #mods > 0 then
			runes[#runes + 1] = { name = name, mods = mods, constraints = constraints }
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

-- SetSelItemId's nodeId branch does register the jewel in spec.jewels (and, when the selected id
-- actually changes, triggers BuildClusterJewelGraphs, which itself rebuilds tree paths). What it
-- does NOT do is rebuild paths when the id is set to the SAME value or when the slot is cleared,
-- so a freshly placed jewel's TREE-modifying effects (alternate class starts, radius/cluster/
-- timeless grants) can silently stay stale. Sync the map from the slot for `socket`, then rebuild
-- paths unconditionally, so both placement and removal are deterministic.
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

-- Item replacement probes bind a PoB output, not a display-group position. Source groups may
-- disappear/reappear during replacement; in particular PoB drops their configured supports.
-- A finite DPS from another group must never masquerade as a measurement of the original skill.
local ITEM_REPLACEMENT_CONTEXT_VERSION = "item_replacement_context_v1"

local function replacementSignature(value)
	if type(value) ~= "table" then return type(value) .. ":" .. tostring(value) end
	local keys, parts = {}, {}
	for key in pairs(value) do keys[#keys + 1] = key end
	table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
	for _, key in ipairs(keys) do
		local name, child = replacementSignature(key), replacementSignature(value[key])
		parts[#parts + 1] = #name .. ":" .. name .. #child .. ":" .. child
	end
	return "{" .. table.concat(parts) .. "}"
end

local function replacementSkillNodes()
	local saved = { elem = "Skills" }
	build.skillsTab:Save(saved)
	for _, child in ipairs(saved) do
		if child.elem == "SkillSet" and tonumber(child.attrib.id) == build.skillsTab.activeSkillSetId then
			return child, saved
		end
	end
	return {}, saved
end

local function replacementGroupSignature(node, sourceKind)
	local normalized = copyTable(node, true)
	-- LoadSkill uses these defaults for every group, including an ordinary secondary group
	-- that has never been selected. Explicit non-first effect selections remain exact.
	for _, key in ipairs({ "mainActiveSkill", "mainActiveSkillCalcs" }) do
		if not normalized.attrib[key] or normalized.attrib[key] == "nil" then normalized.attrib[key] = "1" end
	end
	if sourceKind ~= "ordinary" then
		-- Native derived groups are created before these save/load defaults are materialised.
		if not normalized.attrib.includeInFullDPS or normalized.attrib.includeInFullDPS == "nil" then
			normalized.attrib.includeInFullDPS = "false"
		end
	end
	if sourceKind == "item" then
		-- Item IDs/names belong to the replaced item. Its owning slot and stable root effect
		-- are bound separately. A grant may legitimately change level; user support settings may not.
		normalized.attrib.source = nil
		if normalized[1] and normalized[1].attrib then normalized[1].attrib.level = nil end
	end
	for _, gem in ipairs(normalized) do
		if gem.elem == "Gem" and (not gem.attrib.count or gem.attrib.count == "nil") then
			gem.attrib.count = "1" -- PoB LoadSkill's documented count default
		end
		if gem.elem == "Gem" then
			for _, key in ipairs({ "statSetIndex", "statSetIndexCalcs" }) do
				if gem.attrib[key] == "nil" then gem.attrib[key] = nil end
			end
			for _, key in ipairs({ "corrupted", "enableGlobal2" }) do
				if not gem.attrib[key] or gem.attrib[key] == "nil" then gem.attrib[key] = "false" end
			end
			if not gem.attrib.corruptLevel or gem.attrib.corruptLevel == "nil" then gem.attrib.corruptLevel = "0" end
		end
	end
	return replacementSignature(normalized)
end

local function replacementGroupIdentity(group, ordinal)
	local root = group.gemList and group.gemList[1]
	local kind = group.sourceItem and "item" or group.sourceNode and "tree" or group.source and "other" or "ordinary"
	return {
		sourceKind = kind,
		ordinaryGroupOrdinal = kind == "ordinary" and ordinal or nil,
		ownerSlot = kind == "item" and group.slot or nil,
		sourceIdentity = kind ~= "ordinary" and kind ~= "item" and group.source or nil,
		rootSkillId = kind ~= "ordinary" and root and root.skillId or nil,
	}
end

-- Read-only restoration evidence. The XML input hash intentionally excludes the CALCS tab.
function methods.item_replacement_selection()
	local groups = build.skillsTab.socketGroupList or {}
	local function selected(index, calcs)
		local group = groups[index]
		if not group then return { groupIndex = index or 1, missing = true } end
		local activeIndex = (calcs and group.mainActiveSkillCalcs or group.mainActiveSkill) or 1
		local active = group.displaySkillList and group.displaySkillList[activeIndex]
		local effect = active and active.activeEffect and active.activeEffect.grantedEffect
		return { groupIndex = index, activeSkillIndex = activeIndex, effectId = effect and effect.id,
			weaponSet = build.skillsTab:GetSocketGroupWeaponSet(group), source = group.source,
			rootSkillId = group.gemList and group.gemList[1] and group.gemList[1].skillId }
	end
	return { main = selected(build.mainSocketGroup or 1, false),
		calcs = selected(build.calcsTab.input.skill_number or 1, true),
		activeSkillSetId = build.skillsTab.activeSkillSetId,
		activeItemSetId = build.itemsTab.activeItemSetId,
		secondWeaponSet = build.itemsTab.activeItemSet.useSecondWeaponSet and true or false }
end

local function resolveItemReplacementContext(expected, selectTarget, allowUnselected)
	local list = build.skillsTab.socketGroupList or {}
	local nodes = replacementSkillNodes()
	local mainIndex = build.mainSocketGroup or 1
	local main = list[mainIndex]
	if not expected then
		if not main then return nil, "item_replacement_context_missing" end
		if (main.mainActiveSkill or 1) ~= (main.mainActiveSkillCalcs or main.mainActiveSkill or 1)
			or (build.calcsTab.input.skill_number and build.calcsTab.input.skill_number ~= mainIndex) then
			return nil, "item_replacement_context_mismatch"
		end
		local activeIndex = main.mainActiveSkillCalcs or main.mainActiveSkill or 1
		local active = main.displaySkillList and main.displaySkillList[activeIndex]
		local effect = active and active.activeEffect and active.activeEffect.grantedEffect
		if not effect or not effect.id then return nil, "item_replacement_context_missing" end
		local ordinal = 0
		for index, group in ipairs(list) do
			if group.source == nil then ordinal = ordinal + 1 end
			if index == mainIndex then break end
		end
		expected = replacementGroupIdentity(main, ordinal)
		expected.contextVersion = ITEM_REPLACEMENT_CONTEXT_VERSION
		expected.activeSkillSetId = build.skillsTab.activeSkillSetId
		expected.effectId = effect.id
		expected.skillName = skillNameAt(mainIndex, activeIndex)
		expected.groupConfigSignature = replacementGroupSignature(nodes[mainIndex], expected.sourceKind)
		expected.noSupports = main.noSupports and true or false
	end
	if expected.contextVersion ~= ITEM_REPLACEMENT_CONTEXT_VERSION
		or expected.activeSkillSetId ~= build.skillsTab.activeSkillSetId
		or type(expected.effectId) ~= "string" or type(expected.skillName) ~= "string"
		or type(expected.groupConfigSignature) ~= "string" then
		return nil, "item_replacement_context_mismatch"
	end
	local matchIndex, matchActive, ordinal = nil, nil, 0
	for index, group in ipairs(list) do
		if group.source == nil then ordinal = ordinal + 1 end
		local identity = replacementGroupIdentity(group, ordinal)
		local matches = identity.sourceKind == expected.sourceKind
		for _, key in ipairs({ "ordinaryGroupOrdinal", "ownerSlot", "sourceIdentity", "rootSkillId" }) do
			if identity[key] ~= expected[key] then matches = false end
		end
		if matches then
			for activeIndex, active in ipairs(group.displaySkillList or {}) do
				local effect = active.activeEffect and active.activeEffect.grantedEffect
				if effect and effect.id == expected.effectId and skillNameAt(index, activeIndex) == expected.skillName then
					if matchIndex then return nil, "item_replacement_context_ambiguous" end
					matchIndex, matchActive = index, activeIndex
				end
			end
		end
	end
	if not matchIndex then return nil, "item_replacement_context_mismatch" end
	local selected = list[matchIndex]
	if expected.weaponSet and build.skillsTab:GetSocketGroupWeaponSet(selected) ~= expected.weaponSet then
		return nil, "item_replacement_context_mismatch"
	end
	if replacementGroupSignature(nodes[matchIndex], expected.sourceKind) ~= expected.groupConfigSignature
		or (selected.noSupports and true or false) ~= expected.noSupports then
		return nil, "item_replacement_group_config_changed"
	end
	if mainIndex ~= matchIndex or (selected.mainActiveSkill or 1) ~= matchActive
		or (selected.mainActiveSkillCalcs or selected.mainActiveSkill or 1) ~= matchActive
		or build.calcsTab.input.skill_number ~= matchIndex then
		if selectTarget then
			selectMainSocketGroup(matchIndex, matchActive)
			-- Re-selection may itself refresh source groups. Verify again without mutating.
			return resolveItemReplacementContext(expected, false)
		elseif not allowUnselected then
			return nil, "item_replacement_context_mismatch"
		end
	end
	local resolved = copyTable(expected, true)
	resolved.groupIndex, resolved.activeSkillIndex = matchIndex, matchActive
	resolved.selectionMatches = mainIndex == matchIndex and (selected.mainActiveSkill or 1) == matchActive
		and (selected.mainActiveSkillCalcs or selected.mainActiveSkill or 1) == matchActive
		and build.calcsTab.input.skill_number == matchIndex
	resolved.weaponSet = build.skillsTab:GetSocketGroupWeaponSet(selected)
	resolved.rootLevel = selected.source and selected.gemList and selected.gemList[1] and selected.gemList[1].level or nil
	return resolved
end

-- Internal Python helper; intentionally not a public MCP tool. Never changes selection.
function methods.item_replacement_context(p)
	local context, code = resolveItemReplacementContext(p and p.expectedContext, false, p and p.expectedContext ~= nil)
	if code == "item_replacement_context_missing" and not (p and p.expectedContext) then
		return { ok = true, contextStatus = "no_active_output" }
	end
	return context and { ok = true, calculationContext = context } or { ok = false, errorCode = code }
end

local function isNativeDerivedReplacementGroup(group)
	-- CalcSetup synthesises hidden, triggered, unsupported effects without an item/node
	-- group owner. User groups and ordinary grants do not have this typed provenance.
	if not group.source or group.sourceItem or group.sourceNode or not group.noSupports
		or #(group.gemList or {}) == 0 then return false end
	for _, gem in ipairs(group.gemList) do
		local effect = gem.grantedEffect or (gem.gemData and gem.gemData.grantedEffect)
		if not gem.triggered or not gem.noSupports or gem.fromItem or gem.fromNode
			or not effect or not effect.hidden then return false end
	end
	return true
end

local function replacementDerivedPolicy(snapshot)
	local known, defaults = {}, {}
	local nodes = replacementSkillNodes()
	for index, group in ipairs(build.skillsTab.socketGroupList or {}) do
		if isNativeDerivedReplacementGroup(group) then
			local key = replacementSignature(replacementGroupIdentity(group))
			if known[key] then return nil, "item_replacement_derived_identity_ambiguous" end
			known[key] = replacementGroupSignature(nodes[index], "other")
		end
	end
	if next(known) == nil then return { known = known, defaults = defaults } end
	-- Ask pinned PoB to recreate its own default groups once. Their labels and flags are
	-- engine data, not skill-name heuristics. No generated settings are copied into user groups.
	local calibrated = pcall(function()
		local list = build.skillsTab.socketGroupList
		for index = #list, 1, -1 do
			if isNativeDerivedReplacementGroup(list[index]) then table.remove(list, index) end
		end
		build.buildFlag, build.modFlag = true, true
		runCallback("OnFrame")
		local regeneratedNodes = replacementSkillNodes()
		for index, group in ipairs(build.skillsTab.socketGroupList or {}) do
			if isNativeDerivedReplacementGroup(group) then
				local key = replacementSignature(replacementGroupIdentity(group))
				defaults[key] = known[key] == replacementGroupSignature(regeneratedNodes[index], "other")
			end
		end
	end)
	local restored = pcall(function() loadBuildFromXML(snapshot); runCallback("OnFrame") end)
	if not calibrated or not restored then return nil, "item_replacement_derived_calibration_failed" end
	return { known = known, defaults = defaults }
end

local function replacementInputGuard(targetSlot, derivedPolicy)
	local nodes, skills = replacementSkillNodes()
	local ordinary, sources = {}, {}
	for index, group in ipairs(build.skillsTab.socketGroupList or {}) do
		local derivedIsDefault = false
		if targetSlot and derivedPolicy and isNativeDerivedReplacementGroup(group) then
			local key = replacementSignature(replacementGroupIdentity(group))
			-- A new native group can only have been generated by these item probes. Existing
			-- groups are disposable only when PoB reproduced their exact default configuration.
			derivedIsDefault = not derivedPolicy.known[key] or derivedPolicy.defaults[key] == true
		end
		if not group.source then
			ordinary[#ordinary + 1] = replacementGroupSignature(nodes[index], "ordinary")
		elseif not derivedIsDefault and (not targetSlot or group.slot ~= targetSlot or #(group.gemList or {}) > 1 or group.enabled == false
			or (group.label and group.label ~= "") or group.includeInFullDPS or group.groupCount) then
			-- Keep all non-target source groups and all user-configured target source groups.
			-- New unconfigured grants from the replacement may be discovered by PoB normally.
			local identity = replacementGroupIdentity(group)
			local key = replacementSignature(identity)
			if sources[key] then return nil end -- ambiguous source ownership cannot be carried
			sources[key] = replacementGroupSignature(nodes[index], identity.sourceKind)
		end
	end
	local inactive = {}
	for _, set in ipairs(skills) do
		if tonumber(set.attrib.id) ~= build.skillsTab.activeSkillSetId then
			local savedSet = { attrib = set.attrib }
			for _, node in ipairs(set) do savedSet[#savedSet + 1] = replacementGroupSignature(node, "ordinary") end
			inactive[#inactive + 1] = savedSet
		end
	end
	local slots = {}
	for name, slot in pairs(build.itemsTab.slots) do
		if name ~= targetSlot and slot.selItemId and slot.selItemId ~= 0 then
			local item = build.itemsTab.items[slot.selItemId]
			slots[name] = { id = slot.selItemId, active = slot.active and true or false, raw = item and item.raw }
		end
	end
	local configs = {}
	for id, config in pairs(build.configTab.configSets) do
		configs[id] = { inputs = {}, customModifierBlocks = copyTable(config.customModsList or {}, true) }
		for key, value in pairs(config.input) do
			if value ~= build.configTab:GetDefaultState(key, type(value)) then configs[id].inputs[key] = value end
		end
	end
	local skillSettings = copyTable(skills.attrib, true)
	if skillSettings.defaultGemQuality == "nil" then skillSettings.defaultGemQuality = "0" end
	local allocated = {}
	for nodeId in pairs(build.spec.allocNodes or {}) do allocated[#allocated + 1] = nodeId end
	table.sort(allocated)
	return replacementSignature({
		ordinary = ordinary, sources = sources, inactiveSkills = inactive, skillSettings = skillSettings,
		slots = slots, configs = configs, configSet = build.configTab.activeConfigSetId,
		itemSet = build.itemsTab.activeItemSetId, secondWeaponSet = build.itemsTab.activeItemSet.useSecondWeaponSet and true or false,
		allocatedNodes = allocated, specId = build.treeTab.activeSpec,
	})
end

local function replacementDefenseOnly(keys)
	-- These PoB outputs do not select an offensive effect. Unknown keys still require a target;
	-- absence of a skill must not block pure defense/attribute searches on a new build.
	local permitted = {
		Life = true, LifeUnreserved = true, LifeReserved = true, LifeReservedPercent = true,
		Mana = true, ManaUnreserved = true, ManaReserved = true, ManaReservedPercent = true,
		EnergyShield = true, Armour = true, Evasion = true, Ward = true, TotalEHP = true,
		Str = true, Dex = true, Int = true, ReqStr = true, ReqDex = true, ReqInt = true,
		Spirit = true, SpiritReserved = true, SpiritUnreserved = true,
		FireResist = true, ColdResist = true, LightningResist = true, ChaosResist = true,
		FireResistTotal = true, ColdResistTotal = true, LightningResistTotal = true, ChaosResistTotal = true,
		PhysicalMaximumHitTaken = true, FireMaximumHitTaken = true, ColdMaximumHitTaken = true,
		LightningMaximumHitTaken = true, ChaosMaximumHitTaken = true,
		LifeRegen = true, LifeRegenRecovery = true, ManaRegen = true, EnergyShieldRegen = true,
		BlockChance = true, SpellBlockChance = true, EvadeChance = true,
		MovementSpeedMod = true, EffectiveMovementSpeedMod = true,
	}
	if #keys == 0 then return false end
	for _, key in ipairs(keys) do if not permitted[key] then return false end end
	return true
end

local function evaluateItemReplacements(p)
	local keys, snapshot = p.keys or { "TotalDPS" }, build:SaveDB("code")
	local context, initialError = resolveItemReplacementContext(nil, false)
	if initialError == "item_replacement_context_missing" and replacementDefenseOnly(keys) then initialError = nil end
	local restoreGuard = replacementInputGuard(nil)
	local derivedPolicy, derivedError = replacementDerivedPolicy(snapshot)
	if not derivedError and replacementInputGuard(nil) ~= restoreGuard then
		derivedError = "item_replacement_derived_restore_mismatch"
	end
	initialError = initialError or derivedError
	local guard = replacementInputGuard(p.slot, derivedPolicy)
	local out, failures, contexts = {}, {}, {}
	local reloadNext, fallbackCount = false, 0
	local function probe(raw, fullReload)
		if fullReload then loadBuildFromXML(snapshot) end
		local slot = build.itemsTab.slots[p.slot]
		if not slot then return nil, "item_replacement_slot_missing" end
		local equipped = equipItemRaw(raw, p.slot)
		if not equipped then return nil, "item_replacement_equip_failed" end
		local jewelId = p.slot:match("^Jewel (%d+)$")
		if jewelId then syncJewelSocket(tonumber(jewelId)) end
		if p.isolateEachItem then loadBuildFromXML(build:SaveDB("code")) end
		runCallback("OnFrame")
		if not guard or replacementInputGuard(p.slot, derivedPolicy) ~= guard then
			return nil, "item_replacement_input_changed"
		end
		local resolved, code
		if context then
			resolved, code = resolveItemReplacementContext(context, true)
			if not resolved then return nil, code end
		end
		if replacementInputGuard(p.slot, derivedPolicy) ~= guard then return nil, "item_replacement_input_changed" end
		return { stats = collectStats(keys), context = resolved }
	end
	local completed, exception = pcall(function()
		for index, raw in ipairs(p.items) do
			local result, code
			if initialError then
				code = initialError
			else
				result, code = probe(raw, p.isolateEachItem or reloadNext)
				if not result and not p.isolateEachItem then
					-- A previous candidate may have disabled another slot or removed a source group.
					-- Retry from the immutable input once; never repair user skills or guess a target.
					fallbackCount = fallbackCount + 1
					result, code = probe(raw, true)
				end
			end
			reloadNext = not result
			out[index] = result and result.stats or false
			failures[index] = code or false
			if result and result.context then
				local resolved = result.context
				contexts[index] = {
					groupIndex = resolved.groupIndex, activeSkillIndex = resolved.activeSkillIndex,
					effectId = resolved.effectId, skillName = resolved.skillName,
					sourceKind = resolved.sourceKind, ownerSlot = resolved.ownerSlot,
				}
			else
				contexts[index] = false
			end
			reclaimCalculationGarbage()
		end
	end)
	local restored = pcall(function() loadBuildFromXML(snapshot); runCallback("OnFrame") end)
	if not completed then
		for index in ipairs(p.items) do out[index], failures[index], contexts[index] = false, "item_replacement_probe_failed", false end
	end
	if restored then
		local restoredContext = not context or resolveItemReplacementContext(context, false)
		restored = restoredContext ~= nil and replacementInputGuard(nil) == restoreGuard
	end
	return {
		ok = completed and restored, contextVersion = ITEM_REPLACEMENT_CONTEXT_VERSION,
		calculationContext = context, results = out, failureCodes = failures, resolvedContexts = contexts,
		fallbackCount = fallbackCount, rolledBack = restored, recoveryRequired = not restored,
		errorCode = not completed and "item_replacement_probe_failed" or not restored and "item_replacement_restore_failed" or nil,
		error = not completed and tostring(exception) or nil,
	}
end

-- Batch-evaluate many candidate items in one slot, returning each one's requested stats. Used by
-- the gear optimizer to score crafted candidates in a single round-trip. Restores the build after.
function methods.eval_items(p)
	assert(p and p.slot and type(p.items) == "table", "eval_items requires slot + items[]")
	if p.replacementContext then return evaluateItemReplacements(p) end
	local keys = p.keys or { "TotalDPS" }
	local snapshot = build:SaveDB("code")
	local out = {}
	for i, raw in ipairs(p.items) do
		if p.isolateEachItem then
			-- Each complete replacement starts from the immutable input. Never recalculate
			-- an empty intermediate weapon slot: PoB would discard a dependent offhand.
			loadBuildFromXML(snapshot)
		end
		local ok = equipItemRaw(raw, p.slot)
		if ok then
			local _, slotId = p.slot:match("^Jewel (%d+)$")
			if slotId then
				-- register a jewel candidate in the tree so radius/Time-Lost grants are
				-- actually computed (SetSelItemId alone may skip the path rebuild)
				syncJewelSocket(tonumber(slotId))
			end
			if p.isolateEachItem then
				-- Rebuild from actual persisted item data so stale Rune modifier caches cannot
				-- survive the slot replacement even when the visible item text changed.
				loadBuildFromXML(build:SaveDB("code"))
			end
			runCallback("OnFrame")
			out[i] = collectStats(keys)
		else
			out[i] = false -- candidate failed to parse/equip
		end
		reclaimCalculationGarbage()
	end
	loadBuildFromXML(snapshot)
	runCallback("OnFrame")
	return { results = out }
end

-- Read-only: dump the programmatically generated unique item texts (Data/Uniques/Special/
-- Generated.lua fills data.uniques.generated at engine boot). Each entry is the canonical
-- PoB unique text block; the physical-graph exporter persists them so the static block parser
-- can ingest them without re-evaluating Lua.
function methods.dump_generated_uniques(p)
	p = p or {}
	local uniques = data.uniques.generated or {}
	local out = {}
	for i = 1, #uniques do
		out[#out + 1] = tostring(uniques[i])
	end
	return { uniqueCount = #out, uniques = out }
end

-- Read-only: return a gem's per-level requirements (levelRequirement + attribute weights) so the
-- leveled-build kernel can decide whether a skill is usable at a given character level. The
-- corpus has no reliable gem level data; PoB owns the real levelRequirement curve. Never mutates
-- the build.
function methods.gem_level_requirements(p)
	p = p or {}
	local name = tostring(p.gem_name or "")
	local lookupName = name:lower()
	local gemId = build.data and build.data.gemForBaseName
		and (build.data.gemForBaseName[lookupName] or build.data.gemForBaseName[lookupName .. " support"])
	local gemData = gemId and build.data.gems and build.data.gems[gemId] or nil
	if not gemData or not gemData.grantedEffect then
		return { found = false, gemName = name }
	end
	local ge = gemData.grantedEffect
	if not ge.levels then
		return { found = false, gemName = name }
	end
	local out = {}
	-- Numeric loop instead of ipairs: a hole in the level table must not truncate the curve
	-- (ipairs stops at the first nil), and a missing/zero requirement must not read as "usable
	-- at any level" (asNumber(nil) is 0).
	local n = #ge.levels
	for level = 1, n do
		local levelData = ge.levels[level]
		if levelData and levelData.levelRequirement then
			out[#out + 1] = {
				level = level,
				levelRequirement = asNumber(levelData.levelRequirement),
			}
		end
	end
	return {
		found = true,
		gemName = ge.name or name,
		isSupport = ge.support and true or false,
		naturalMaxLevel = asNumber(gemData.naturalMaxLevel),
		levels = out,
	}
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
	local gemAvailabilitySubjects = {}
	for groupIndex, group in ipairs(build.skillsTab.socketGroupList or {}) do
		if group.enabled ~= false then
			for _, gem in ipairs(gemSummaryForSocketGroup(groupIndex)) do
				if gem.enabled then
					gemAvailabilitySubjects[#gemAvailabilitySubjects + 1] = {
						groupIndex = groupIndex, name = gem.name, gemId = gem.gemId,
						gameId = gem.gameId, effectId = gem.effectId,
						source = group.source,
						sourceKind = group.sourceItem and "item" or group.sourceNode and "tree" or group.source and "other" or "ordinary",
					}
				end
			end
		end
	end
	local allocatedPassiveJewelSocketIds = {}
	for _, socket in ipairs(methods.list_jewel_sockets().sockets) do
		if socket.allocated then allocatedPassiveJewelSocketIds[#allocatedPassiveJewelSocketIds + 1] = socket.socket end
	end
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
	local spiritAvailable = asOptionalNumber(mainOutput.Spirit)
	local spiritReservedCapped = asOptionalNumber(mainOutput.SpiritReserved)
	local spiritUnreserved = asOptionalNumber(mainOutput.SpiritUnreserved)
	local spiritRequested = spiritAvailable and spiritUnreserved
		and (spiritAvailable - spiritUnreserved) or nil
	local spiritOverBy = spiritUnreserved and math.max(0, -spiritUnreserved) or nil
	local charmLimit = asOptionalNumber(mainOutput.CharmLimit)
	if charmLimit == nil then
		local mainEnv = build.calcsTab and build.calcsTab.mainEnv
		local modDB = mainEnv and mainEnv.modDB
		if modDB then
			charmLimit = math.min(
				modDB:Override(nil, "CharmLimit") or modDB:Sum("BASE", nil, "CharmLimit"),
				3
			)
		end
	end
	local activeWeaponSet = build.itemsTab and build.itemsTab.activeItemSet
		and build.itemsTab.activeItemSet.useSecondWeaponSet and 2 or 1
	local r = {
		class = spec.curClassName,
		ascendancy = spec.curAscendClassName,
		level = build.characterLevel,
		treeVersion = spec.treeVersion,
		latestTreeVersion = latestTreeVersion,
		mainSkill = mainSkillName(),
		mainSkillWeaponCheck = activeWeaponCheck(build.mainSocketGroup or 1),
		mainSkillGroup = gems,
		gemAvailabilitySubjects = gemAvailabilitySubjects,
		activeSkillGemLevelViolations = activeGemLevelViolations(),
		notables = notables,
		keystones = keystones,
		defenseMechanics = defenseMechanics(mainOutput),
		ascendancyNotables = asc,
		gear = gear,
		allocatedPassiveJewelSocketIds = allocatedPassiveJewelSocketIds,
		customMods = activeCustomMods(),
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
		attributeRequirementSources = attributeRequirementSources(),
		spiritAvailable = spiritAvailable,
		spiritReservedCapped = spiritReservedCapped,
		spiritUnreserved = spiritUnreserved,
		spiritRequested = spiritRequested,
		spiritOverBy = spiritOverBy,
		-- Compatibility alias.  SpiritReserved is capped at available Spirit, so it cannot
		-- represent actual demand when the source is over-reserved.
		spiritUsed = spiritRequested,
		activeWeaponSet = activeWeaponSet,
		charmLimit = charmLimit,
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

function methods.select_judge_skill(p)
	p = p or {}
	local selected = selectJudgeSkillForGroup(
		p.offenseSkillGroupIndex,
		p.expectedSkillName
	)
	if not selected then
		return {
			status = "error",
			errorCode = "selected_skill_conflict",
		}
	end
	return {
		status = "selected",
		selectedSkill = selected,
		selectedSkillGroup = gemSummaryForSocketGroup(selected.groupIndex),
		supplementalSkills = judgeSupplementalSkillSummaries(),
		calculationContext = {
			groupIndex = selected.groupIndex,
			activeIndex = selected.activeIndex,
			skillName = selected.skillName,
			sourceMetric = selected.sourceMetric,
		},
	}
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
		defenseMechanics = defenseMechanics(o),
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
	local pathNodeIds = {}
	local pathSeen = {}
	for _, pathNode in ipairs(n.path or {}) do
		if pathNode.id and not pathSeen[pathNode.id] then
			pathSeen[pathNode.id] = true
			pathNodeIds[#pathNodeIds + 1] = pathNode.id
		end
	end
	table.sort(pathNodeIds)
	local attributeOptions = {}
	local sourceNode = build.spec.tree.nodes[n.id]
	if sourceNode and sourceNode.isAttribute then
		for _, option in ipairs(sourceNode.options or {}) do
			attributeOptions[#attributeOptions + 1] = option.dn
		end
	end
	return {
		id = n.id,
		name = n.name,
		type = n.type,
		stats = n.sd,
		alloc = n.alloc or false,
		pathDist = n.pathDist,
		reachable = n.path ~= nil,
		ascendancy = n.ascendancyName,
		pathNodeIds = pathNodeIds,
		isAttribute = sourceNode and sourceNode.isAttribute or false,
		attribute = sourceNode and sourceNode.isAttribute and n.dn or nil,
		attributeOptions = attributeOptions,
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
				local nodeRank = node.alloc and 0 or (node.path and 1 or 2)
				local bestRank = best and (best.alloc and 0 or (best.path and 1 or 2)) or 3
				local nodeDist = node.pathDist or 1e9
				local bestDist = best and (best.pathDist or 1e9) or 1e9
				if
					not best
					or nodeRank < bestRank
					or (nodeRank == bestRank and nodeDist < bestDist)
					or (nodeRank == bestRank and nodeDist == bestDist and (node.id or 0) < (best.id or 0))
				then
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
	-- most matched terms first, then reachable (lowest pathDist), then name/id for a stable order
	table.sort(scored, function(a, b)
		if a.score ~= b.score then
			return a.score > b.score
		end
		local pa, pb = a.node.pathDist or 1e9, b.node.pathDist or 1e9
		if pa ~= pb then
			return pa < pb
		end
		local na, nb = a.node.name or "", b.node.name or ""
		if na ~= nb then return na < nb end
		return (a.node.id or 0) < (b.node.id or 0)
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

-- Return a bounded set of ordinary allocated leaf nodes that can be removed without tearing down
-- another allocated branch. Python measures their real stat loss before considering an equal-point
-- jewel-socket swap; this is intentionally not a global passive-tree optimizer.
function methods.list_reallocation_candidates(p)
	p = p or {}
	local requestedLimit = tonumber(p.limit)
	local limit = requestedLimit and math.max(1, math.min(32, requestedLimit)) or nil
	local out = {}
	for _, node in pairs(build.spec.allocNodes or {}) do
		local nodeType = node.type
		if
			node.alloc
			and not node.ascendancyName
			and (nodeType == "Normal" or nodeType == "Notable")
			and #(node.depends or {}) == 1
		then
			local summary = nodeSummary(node)
			summary.pointsFreed = 1
			out[#out + 1] = summary
		end
	end
	table.sort(out, function(a, b)
		if a.type ~= b.type then return a.type == "Normal" end
		return (a.id or 0) < (b.id or 0)
	end)
	local candidateCount = #out
	if limit then
		while #out > limit do table.remove(out) end
	end
	return {
		candidates = out,
		candidateCount = candidateCount,
		returnedCount = #out,
		truncated = limit and #out < candidateCount or false,
		boundedLimit = limit,
	}
end

function methods.alloc_passive(p)
	local attributeIndex
	if p and p.path_attribute ~= nil then
		attributeIndex = ({ Strength = 1, Dexterity = 2, Intelligence = 3 })[p.path_attribute]
		if not attributeIndex then return { ok = false, errorCode = "invalid_passive_attribute" } end
	end
	local n = findNode(p and p.node)
	if not n then return { ok = false, error = "node not found" } end
	if n.alloc then return { ok = true, already = true, node = nodeSummary(n) } end
	if not n.path then return { ok = false, error = "node not reachable from current tree" } end
	local before = statSnapshot()
	local used = build.spec:CountAllocNodes()
	-- Use the pinned PoB allocation policy only for this request. Never persist a hidden default
	-- that could change subsequent allocations made by another tool or imported build.
	local previousAttributeIndex = build.spec.attributeIndex
	if attributeIndex then build.spec.attributeIndex = attributeIndex end
	local allocated, allocationError = pcall(function() build.spec:AllocNode(n, nil) end)
	build.spec.attributeIndex = previousAttributeIndex
	if not allocated then error(allocationError) end
	build.buildFlag = true
	runCallback("OnFrame")
	local usedAfter = build.spec:CountAllocNodes()
	local r = {
		ok = true,
		node = nodeSummary(build.spec.nodes[n.id]),
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

function methods.set_passive_attribute(p)
	local attributeIndex = p and ({ Strength = 1, Dexterity = 2, Intelligence = 3 })[p.attribute]
	if not attributeIndex then return { ok = false, errorCode = "invalid_passive_attribute" } end
	local n = findNode(p and p.node)
	if not n then return { ok = false, errorCode = "passive_node_not_found" } end
	local sourceNode = build.spec.tree.nodes[n.id]
	if not sourceNode or not sourceNode.isAttribute then
		return { ok = false, errorCode = "passive_node_not_attribute" }
	end
	if not n.alloc then return { ok = false, errorCode = "passive_node_not_allocated" } end
	if n.dn == p.attribute then
		return { ok = true, already = true, node = nodeSummary(n), pointsSpent = 0 }
	end
	local before = statSnapshot()
	build.spec:SwitchAttributeNode(n.id, attributeIndex)
	build.spec:BuildAllDependsAndPaths()
	build.buildFlag = true
	runCallback("OnFrame")
	return {
		ok = true, node = nodeSummary(build.spec.nodes[n.id]), pointsSpent = 0,
		statsDelta = statDelta(before),
	}
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
		table.sort(reportKeys)
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
						local requiredPathIds = {}
						local requiredSeen = {}
						for _, pathNode in ipairs(n.path or {}) do
							if pathNode.id and not requiredSeen[pathNode.id] then
								requiredSeen[pathNode.id] = true
								requiredPathIds[#requiredPathIds + 1] = pathNode.id
							end
						end
						if n.id and not requiredSeen[n.id] then requiredPathIds[#requiredPathIds + 1] = n.id end
						table.sort(requiredPathIds)
						local u0 = spec:CountAllocNodes()
						spec:AllocNode(n, nil)
						build.buildFlag = true
						runCallback("OnFrame")
						requiredSpent = requiredSpent + (spec:CountAllocNodes() - u0)
						chosen[#chosen + 1] = {
							name = n.name,
							id = n.id,
							required = true,
							pathNodeIds = requiredPathIds,
						}
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
			for _, m in ipairs(reportKeys) do
				local w = goals[m]
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

			local best, bestGain, bestScore, bestCost, bestPathIds
			for i = 1, math.min(#cands, cap) do
				local node = cands[i]
				local pathNodes = {}
				local pathIds = {}
				local pathSeen = {}
				for _, pn in ipairs(node.path) do
					pathNodes[pn] = true
					if pn.id and not pathSeen[pn.id] then
						pathSeen[pn.id] = true
						pathIds[#pathIds + 1] = pn.id
					end
				end
				pathNodes[node] = true
				if node.id and not pathSeen[node.id] then pathIds[#pathIds + 1] = node.id end
				table.sort(pathIds)
				local gain = scoreGain(calcBase, calcFunc({ addNodes = pathNodes }))
				reclaimCalculationGarbage()
				-- Quantize the score before comparison so insignificant floating-point noise cannot change
				-- the selected node across processes/platforms. Cost and node id complete the total order.
				local score = tonumber(string.format("%.12g", gain)) or gain
				local betterTie = best
					and score == bestScore
					and (node.pathDist < bestCost or (node.pathDist == bestCost and node.id < best.id))
				if score > 0 and (not best or score > bestScore or betterTie) then
					best, bestGain, bestScore, bestCost, bestPathIds =
						node, gain, score, node.pathDist, pathIds
				end
			end

			if not best then
				break
			end
			spec:AllocNode(best, nil)
			build.buildFlag = true
			runCallback("OnFrame")
			chosen[#chosen + 1] = {
				name = best.name,
				id = best.id,
				cost = bestCost,
				gain = bestGain,
				score = bestScore,
				type = nodeType,
				pathNodeIds = bestPathIds,
			}
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
		optimizerVersion = p.optimizerVersion or "greedy_v1",
		metric = p.goals and "weighted" or metric,
		pointsUsed = used,
		pointsRemaining = unspent,
		smallNodePoints = smallUsed,
		requiredPoints = requiredSpent,
		allocated = chosen,
	}
	local allocatedNodeIds = {}
	for _, node in pairs(spec.allocNodes or {}) do
		if node and node.alloc and node.id then allocatedNodeIds[#allocatedNodeIds + 1] = node.id end
	end
	table.sort(allocatedNodeIds)
	result.allocatedNodeIds = allocatedNodeIds
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
emit(json.encode({
	ready = true,
	runtimeContract = HEADLESS_RUNTIME_CONTRACT,
	jit = jit and jit.version,
	treeVersion = latestTreeVersion,
}))

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
			reclaimCalculationGarbage()
			if ok then
				emit(json.encode({ id = id, ok = true, result = result }))
			else
				emit(json.encode({ id = id, ok = false, error = tostring(result) }))
			end
		end
	end
end
