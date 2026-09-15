# Exile Architect

[English](README.md) · [简体中文](README.zh-CN.md)

**让 AI Agent 帮你研究、创建和理解 Path of Exile 2 构筑（BD）。**

Exile Architect 为 Codex、Claude Code、Cursor 和 OpenCode 接入游戏资料、可复用的构筑知识库与 Headless Path of Building。Agent 负责分析和设计，PoB 负责数值计算与构筑检查。

[安装](#安装) · [使用方式](#使用方式) · [案例](#真实产物案例) · [常见问题](#常见问题)

## 三种工作流

| 我想做什么 | 使用哪个功能 | 会得到什么 |
| --- | --- | --- |
| 从已有 BD 中积累可复用的知识 | **Research · 研究** · `poe-bd-research` | 保存机制、组件配合、成立条件与失败场景，供后续构筑设计检索 |
| 按职业、技能和目标等级设计一个 BD | **Create · 创建** · `poe-bd-create` | 技能、装备与天赋方案，PoB 检查，本地构筑文件与玩法说明 |
| 看懂一个已有 BD，知道怎样使用它 | **Learning · 学习** · `poe-bd-learn` | 带组件图标、战斗循环图、详细讲解、目录与搜索的 HTML 学习指南 |

**Research 积累知识，Create 利用知识设计构筑，Learning 帮玩家读懂构筑而不写入知识库。** 三种功能可以独立使用。

## 安装

当前通过源码安装。安装后请保留项目文件夹，Agent 会从这里启动工具。

### 1. 准备环境

- 安装 [Git](https://git-scm.com/downloads) 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。uv 可以自动安装所需的 Python 版本。
- 准备一个已经配置好模型的宿主：**Codex、Claude Code、Cursor 或 OpenCode**。Research 还需要宿主允许子代理访问 MCP 工具。
- 安装运行 PoB 计算引擎所需的 **LuaJIT 2.1**：

| 系统 | LuaJIT 安装方式 |
| --- | --- |
| Windows | 安装 [MSYS2](https://www.msys2.org/)，打开它的 **UCRT64** 终端，运行 `pacman -S mingw-w64-ucrt-x86_64-luajit`。程序会自动识别标准位置 `C:\msys64\ucrt64\bin\luajit.exe`。 |
| macOS | 已安装 Homebrew 时，运行 [`brew install luajit`](https://formulae.brew.sh/formula/luajit)。 |
| Ubuntu / Debian | 依次运行 `sudo apt-get update` 和 `sudo apt-get install luajit`。 |

LuaJIT 安装在其他位置时，在 Agent 宿主使用的环境中把 `POB_LUAJIT` 设为可执行文件的绝对路径。Node.js 20+ 是可选依赖，用于导出 Build Planner `.build` 文件。

### 2. 下载项目和 PoB

Windows 使用 PowerShell，macOS / Linux 使用终端，依次运行：

```sh
git clone https://github.com/avdergh/poe2-exile-architect.git
cd poe2-exile-architect
uv sync --python 3.12

git clone --filter=blob:none --no-checkout https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2.git pob/PathOfBuilding-PoE2
git -C pob/PathOfBuilding-PoE2 config core.autocrlf false
git -C pob/PathOfBuilding-PoE2 checkout ce566eac45ea8a86477f513c7ee65a1ebe60014e
```

请使用这个固定 PoB 版本，并应用下一步的补丁。仅安装 PoB 桌面软件不能替代这里的 headless 运行时。

### 3. 应用补丁并接入 Agent

选择对应系统的命令。以下以 Codex 为例；使用其他宿主时，将 `codex` 替换为 `claude`、`cursor` 或 `opencode`。

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

补丁只需在新下载的 PoB 源码上应用一次。安装器会注册四个本地 MCP 服务并安装工作流 skills。Windows 是主要开发平台；macOS 尚未完成实机认证。

### 4. 检查是否安装成功

重启 Agent 宿主，打开一个新会话，发送：

```text
检查 Exile Architect 工具是否可用，调用 engine_health，
然后确认可以使用 poe-bd-research、poe-bd-create 和 poe-bd-learn。
```

没有找到工具时，检查宿主 MCP 配置中是否有 `poe_knowledge_mcp`、`poe_build_mcp`、`poe_research_mcp` 和 `poe_learning_mcp`。计算引擎无法启动时，检查上面的 LuaJIT 安装路径与固定 PoB 源码。

## 使用方式

把下面的请求**发送到 Agent 对话中**，需要已有 BD 时附上文件。这些是使用示例，不是终端命令；也可以通过宿主的 skill 菜单选择对应功能。

### Research：把已有 BD 研究成知识

从 PoB 导出构筑的导入码，保存为文本文件。请同时提供这个 BD 的实际游戏版本，便于正确记录知识适用范围。

```text
使用 /poe-bd-research 研究附件 my-build.txt。
这个 BD 的游戏版本是［该构筑的实际补丁号］。
分析核心机制、必需的组件配合和失效条件，
把可复用的研究结论保存到本地知识库。
```

Research 会分析构筑、核对证据，再保存通过验收的知识。后续 Create 可以检索这些知识；你会收到研究成果与待验证问题的摘要。

### Create：设计一个 BD

```text
使用 /poe-bd-create，以 Spark 为核心创建一个 90 级 Sorceress BD。
目标是终局刷图和 Boss。讲清技能组合、装备、天赋与战斗循环，
并导出本地 PoB 文件。
```

Create 直接设计**一个目标等级的 BD**，使用 PoB 检查并解释结果，不需要先提供参考构筑。有匹配的 Research 知识时会用于指导设计；知识不足或机制未建模的部分会在结果中说明。

### Learning：学会理解和使用一个 BD

```text
使用 /poe-bd-learn，面向新手讲解附件 my-build.txt。
先讲战斗循环，再解释技能、装备、天赋、资源恢复与防御层。
生成一份中文 HTML 学习指南。
```

用浏览器打开生成的 HTML 文件即可阅读。指南包含组件讲解、机制图与搜索，可以从头学习，也可以直接查某个部位。Learning 不写入 Research 知识，也不生成新的 BD。

输出语言默认跟随你的请求，也可以明确指定其他语言。

## 真实产物案例

- [Twister 完整学习指南](examples/learning-twister.zh-CN.md)：100 级 Gemling Legionnaire 的 14 章正文、组件与概念说明，可直接阅读，也可下载带图标、搜索和交互说明的 HTML 原版。
- [95 级 Twister 构筑](examples/create-latest.zh-CN.md)：2026-09-12 的最新本地导出，提供完整 PoB 导入码和在线分享链接，可查看实际技能、装备与天赋。

这些案例来自实际产物；Create 以已有生成候选展示，未补验当前版本。

## 常见问题

**需要额外配置模型 API Key 吗？**

使用 Agent 宿主已经配置好的模型即可，Exile Architect 不另行运行模型服务。

**构筑和研究知识保存在哪里？**

默认保存在操作系统的本地用户数据目录 `poe2-build-mcp` 下，可通过 `POE2_MCP_DATA` 指定其他位置。Agent 会返回生成文件的路径。

**能生成从开荒到终局的完整升级路线吗？**

Create 当前交付目标等级的构筑，不提供完整升级路线。Learning 负责讲解你提供的已有构筑。

**“待验证候选”是什么意思？**

部分机制或资源条件还需要验证。报告会区分 PoB 观察、粗估与未知项；通过检查不等于已经证实实战表现。

**`poe-bd-learning-loop` 也是学习指南吗？**

它是另一个实验性流程，用于比较参考构筑与独立生成的构筑，并记录经过审核的经验。想让 Agent 带你读懂一个 BD，请用 `poe-bd-learn`。

**怎样更新？**

在项目目录运行 `git pull --ff-only` 和 `uv sync`，重新运行对应宿主的安装命令并重启宿主。如果固定 PoB 版本发生变化，还需按 [pob/PINNED.md](pob/PINNED.md) 更新 headless 运行时。

## 反馈与贡献

[提交 Issue](https://github.com/avdergh/poe2-exile-architect/issues) 时，请提供宿主、操作系统、游戏版本、复现步骤和错误信息，不要附带凭据或私有构筑导出。提交代码改动时，请附上相关验证结果。

工作流说明：[Research](poe-bd-creator-plugin/skills/poe-bd-research/SKILL.md) · [Create](poe-bd-creator-plugin/skills/poe-bd-create/SKILL.md) · [Learning](poe-bd-creator-plugin/skills/poe-bd-learn/SKILL.md)。

## 许可与致谢

代码采用 [MIT 许可](LICENSE)。本项目基于 [poe2-build-mcp](https://github.com/MaxWilk/poe2-build-mcp) 和 [PathOfBuilding-PoE2](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2)，[转换 provider](providers/poe2-build-converter/UPSTREAM_LICENSE.txt) 保留其上游许可声明。第三方游戏数据和美术的权利归各自权利人所有。

本项目与 Grinding Gear Games 无关联，亦未获得其背书。
