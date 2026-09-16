# Exile Architect

[English](README.md) · [简体中文](README.zh-CN.md)

**Research, create, and understand Path of Exile 2 builds with your AI agent.**

Exile Architect connects Codex, Claude Code, Cursor, and OpenCode to game data, a reusable build knowledge base, and Headless Path of Building. Your agent makes the design decisions; PoB supplies the calculations and build checks.

[Install](#install) · [Use it](#use-it) · [Examples](#real-output-examples) · [FAQ](#common-questions)

## Three workflows

| I want to… | Use | What I get |
| --- | --- | --- |
| Extract useful knowledge from an existing build | **Research** · `poe-bd-research` | Saved explanations of mechanics, component synergies, requirements, and failure cases that future builds can draw on |
| Design a build for a class, skill, and target level | **Create** · `poe-bd-create` | Skill, equipment, and passive choices; PoB checks; local build files and a playstyle explanation |
| Understand how an existing build works | **Learning** · `poe-bd-learn` | An HTML learning guide with component icons, combat-loop diagrams, explanations, navigation, and search |

**Research builds the knowledge base. Create uses it to design builds. Learning teaches you a build without adding it to the knowledge base.** You can use each workflow on its own.

## Install

The current installation uses a source checkout. Keep this folder after installation: the agent runs its tools from here.

### 1. Install the prerequisites

- [Git](https://git-scm.com/downloads) and [uv](https://docs.astral.sh/uv/getting-started/installation/). uv can install the required Python version for you.
- An agent host: **Codex**, **Claude Code**, **Cursor**, **OpenCode**, or **DeepSeek Harness**, with model access already configured. Research requires a host that gives subagents access to MCP tools.
- **LuaJIT 2.1**, used to run the PoB calculation engine:

| System | LuaJIT installation |
| --- | --- |
| Windows | Install [MSYS2](https://www.msys2.org/), open its **UCRT64** terminal, and run `pacman -S mingw-w64-ucrt-x86_64-luajit`. The standard `C:\msys64\ucrt64\bin\luajit.exe` location is detected automatically. |
| macOS | With Homebrew installed, run [`brew install luajit`](https://formulae.brew.sh/formula/luajit). |
| Ubuntu / Debian | Run `sudo apt-get update` followed by `sudo apt-get install luajit`. |

For a nonstandard LuaJIT location, set `POB_LUAJIT` to the executable's absolute path in the environment used by your agent host. Node.js 20+ is optional, for Build Planner `.build` export.

### 2. Download the project and PoB

Run these commands in PowerShell on Windows, or a terminal on macOS / Linux:

```sh
git clone https://github.com/avdergh/poe2-exile-architect.git
cd poe2-exile-architect
uv sync --python 3.12

git clone --filter=blob:none --no-checkout https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2.git pob/PathOfBuilding-PoE2
git -C pob/PathOfBuilding-PoE2 config core.autocrlf false
git -C pob/PathOfBuilding-PoE2 checkout ce566eac45ea8a86477f513c7ee65a1ebe60014e
```

Use this pinned PoB revision with the patches below. Installing the PoB desktop application alone does not supply this headless runtime.

### 3. Apply the patches and connect your agent

Choose your system. The examples install for Codex; replace `codex` with `claude`, `cursor`, or `opencode` for your host. DeepSeek Harness installs through its own preset — see the end of this step.

**Windows PowerShell**

```powershell
Get-ChildItem .\pob\patches\*.patch | Sort-Object Name | ForEach-Object {
    git -C pob/PathOfBuilding-PoE2 apply --ignore-whitespace $_.FullName
    if ($LASTEXITCODE -ne 0) { throw "PoB patch failed: $($_.Name)" }
}
.\install.ps1 -FromCheckout codex
```

**macOS / Linux**

```sh
(cd pob/PathOfBuilding-PoE2 && git apply --ignore-whitespace ../patches/*.patch)
bash install.sh --from-checkout codex
```

Apply the patches once to a fresh PoB checkout. The installer registers the four local MCP servers and installs the workflow skills. Windows is the primary development platform; macOS has not completed real-machine certification.

**DeepSeek Harness**

DeepSeek Harness has a native MCP client, so Exile Architect installs as an agent preset instead of a host config. Finish steps 1 and 2 first: the four MCP servers start the same headless PoB engine, so they need the pinned PoB checkout, its patches, and LuaJIT.

```powershell
.\install.ps1 -FromCheckout dsh
```

```sh
bash install.sh --from-checkout dsh
```

This places the `poe-bd` preset in `${DSH_HOME:-$HOME/.dsh}/.agent-presets/poe-bd` with your checkout path already filled in, and writes a ready-to-use copy of the layer-1 MCP patch beside it. Start DSH, pick **poe-bd** in a new session, then ask it to call `engine_health`. `.\install.ps1 -Doctor dsh` (or `bash install.sh --doctor dsh`) checks the placed preset.

Pick one registration path: either the preset, or `dsh web --patch <preset dir>/poe-bd.mcp.cordis.yml` to register the servers for every session. Applying both starts a second MCP client per server — two PoB engines — and exposes the tools to every session. DeepSeek Harness host acceptance is not complete yet; [DSH setup (Chinese)](dsh/README.md) covers the details and the known limits.

### 4. Verify the installation

Restart your agent host, open a new conversation, and send:

```text
Check that the Exile Architect tools are available. Call engine_health,
then confirm that poe-bd-research, poe-bd-create, and poe-bd-learn are available.
```

If tools are missing, check for `poe_knowledge_mcp`, `poe_build_mcp`, `poe_research_mcp`, and `poe_learning_mcp` in the host's MCP configuration. In DeepSeek Harness the tools appear only in a session that uses the `poe-bd` preset. If the engine cannot start, check LuaJIT and the pinned PoB checkout above.

## Use it

Send these requests **in your agent conversation**, with the relevant file attached. These are example prompts, not terminal commands. You can also select the named skill through your host's skill menu.

### Research — save reusable build knowledge

Export a build from PoB as an import code and save it in a text file. Supply the build's actual game patch so the research can be versioned correctly.

```text
Use /poe-bd-research to study the attached my-build.txt.
Its game patch is [the build's actual patch].
Explain its core mechanics, required synergies, and failure conditions,
and save the reusable findings to the local knowledge base.
```

Research analyzes the build, checks the evidence, and stores accepted findings. Later Create requests can retrieve them. You receive a summary of what was learned and what still needs verification.

### Create — design a build

```text
Use /poe-bd-create to make a level 90 Sorceress build centered on Spark.
Focus on endgame mapping and bosses. Explain the skill setup, equipment,
passives, and combat loop, and export the local PoB files.
```

Create designs **one build at the requested level**, checks it with PoB, and explains the result. You do not need to provide an existing build. Matching Research knowledge guides the design; missing knowledge or unmodelled mechanics are called out in the result.

### Learning — understand a build

```text
Use /poe-bd-learn to explain the attached my-build.txt to a new player.
Start with the combat loop, then explain the skills, equipment, passives,
resource recovery, and defensive layers. Deliver an English HTML guide.
```

Open the generated HTML file in a browser. The guide includes component explanations, diagrams, and search, so you can read from start to finish or look up a specific part. Learning does not write Research knowledge or create a new build.

Outputs follow the language of your request unless you specify another language.

## Real output examples

- [Twister learning guide](examples/learning-twister.en.md): a 14-chapter Chinese guide to a level 100 Gemling Legionnaire, with an English introduction. Learn the combat loop, skill interactions, equipment, and passive choices. Read it online or download the HTML reader with icons, search, and interactive explanations.
- [Level 99 Deadeye Ice Shot candidate](examples/create-latest.en.md): Ice Shot and two Mirage setups, supported by Freezing Mark, Snipe, and Tornado Shot, using endgame trade gear with Headhunter and Lineage supports.

[![Equipment and stats for the level 99 Deadeye Ice Shot build](examples/assets/deadeye-ice-shot-99.jpg)](https://poe.ninja/poe2/pob/29726)

This example includes all four Create deliverables:

| Output | Purpose | View or download |
| --- | --- | --- |
| Complete PoB XML | Inspect and edit skills, equipment, passives, and configuration | [PoB file](examples/Deadeye_Ice_Shot_99.xml) |
| PoB import code | Paste into PoB to import the build | [Import code](examples/Deadeye_Ice_Shot_99.pobcode.txt) |
| Official `.build` file | Import into the official Build Planner | [.build file](examples/Deadeye_Ice_Shot_99.build) |
| Online share page | Browse and share the build | [poe.ninja page](https://poe.ninja/poe2/pob/29726) |

The main Ice Shot reads approximately 126.2k DPS in PoB's Pinnacle boss configuration. Complete damage from the Mirage setups and some recovery mechanics still require verification. Parts of the `.build` export are represented as descriptive text; use PoB for the full configuration. See the [example](examples/create-latest.en.md) for details.

## Common questions

**Do I need my own model API key?**

Use the model access already configured in your agent host. Exile Architect does not run a separate model service.

**Where are my builds and research stored?**

In the operating system's local user-data directory under `poe2-build-mcp`. Set `POE2_MCP_DATA` to use another location. Your agent returns the paths to generated files.

**Can it make a complete leveling guide?**

Create currently delivers a build at a target level, not a full campaign-to-endgame progression. Learning explains the build you supply.

**What does “candidate” mean?**

Some mechanics or resource conditions still need verification. Reports separate PoB observations, estimates, and unknowns; passing a check does not establish in-game performance.

**Is `poe-bd-learning-loop` the Learning guide?**

It is a separate experimental workflow that compares reference builds with independently generated builds and records reviewed lessons. For a player-facing guide, use `poe-bd-learn`.

**How do I update?**

Run `git pull --ff-only` and `uv sync` in the project folder, rerun the installer for your host, and restart it. If the pinned PoB revision changes, also update the headless runtime following [pob/PINNED.md](pob/PINNED.md). Reinstalling the DeepSeek Harness preset keeps the previous version as a `poe-bd.bak` recovery point; the install after that reports a conflict until you pass `-Force` / `--force`, which rotates that recovery point to a timestamped name instead of deleting it.

## Contributing

[Open an issue](https://github.com/avdergh/poe2-exile-architect/issues) with your host, operating system, game patch, steps to reproduce, and the error message. Keep credentials and private build exports out of reports. Pull requests should include relevant verification.

Workflow instructions: [Research](poe-bd-creator-plugin/skills/poe-bd-research/SKILL.md) · [Create](poe-bd-creator-plugin/skills/poe-bd-create/SKILL.md) · [Learning](poe-bd-creator-plugin/skills/poe-bd-learn/SKILL.md).

## License and credits

Code is licensed under [MIT](LICENSE). Built on [poe2-build-mcp](https://github.com/MaxWilk/poe2-build-mcp) and [PathOfBuilding-PoE2](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2); the [converter provider](providers/poe2-build-converter/UPSTREAM_LICENSE.txt) retains its upstream notice. Third-party game data and artwork retain their respective rights.

This product is not affiliated with or endorsed by Grinding Gear Games.
