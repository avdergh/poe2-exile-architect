# poe.ninja freshness fixtures

这些紧凑 JSON fixtures 是手工裁剪的片段，建模自 `server/freshness/ninja.py` 使用的公开
poe.ninja Path of Exile 2 index endpoints。

只保留 Task3 parser 和选择规则需要的字段：league names / API URL tokens、snapshot
versions、`snapshotName`、passive-tree tokens 和 build sample totals。被选中的 league URL
使用 live poe.ninja token 形态（`runesofaldur`），而 `snapshotName` 保留带连字符的展示
slug（`runes-of-aldur`），不能把它当作 API league URL。

fixture 还包含一个带点号的旧 race snapshot URL（`0.4.0act4bosskillrace3ssf`）。它被有意
排除在 `buildLeagues[]` 之外，用来证明归档 snapshot 不会破坏当前 league 选择。
