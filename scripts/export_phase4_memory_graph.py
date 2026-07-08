"""Export a safe Phase 4 research-memory graph visualization.

This script reads durable, already-sanitized Phase 4 tables and writes a
self-contained HTML file. It never reads transient packets or raw mature-build
material.
"""

from __future__ import annotations

import argparse
import html
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("phase4_real_research_memory.sqlite")
DEFAULT_OUTPUT = Path("phase4_memory_graph.html")

RAW_MARKERS = (
    "eNrt",
    "rawXml",
    "rawImportCode",
    "PathOfBuilding",
    "<Build",
    "<Skills",
    "nameSpec",
    "transientPacketPath",
    "transientPromptPath",
    "pobb.in/",
    "poe.ninja/",
    "http://",
    "https://",
)


def build_memory_graph(
    db_path: str | Path,
    *,
    planner_visible_only: bool = True,
    limit_patterns: int = 250,
    limit_edges: int = 250,
    limit_fragments: int = 250,
) -> dict[str, Any]:
    """Read safe memory rows and return a simple graph JSON object."""
    db = Path(db_path)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        tables = _tables(con)
        nodes: dict[str, dict[str, Any]] = {}
        graph_edges: list[dict[str, Any]] = []

        if "research_build_patterns" in tables:
            _add_patterns(
                con,
                nodes,
                graph_edges,
                planner_visible_only=planner_visible_only,
                limit=limit_patterns,
            )
        if "research_semantic_edges" in tables:
            _add_semantic_edges(
                con,
                nodes,
                graph_edges,
                planner_visible_only=planner_visible_only,
                limit=limit_edges,
            )
        if "research_fragments" in tables:
            _add_fragments(con, nodes, graph_edges, limit=limit_fragments)

        graph = {
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "dbPathLabel": db.name,
            "plannerVisibleOnly": planner_visible_only,
            "nodes": sorted(nodes.values(), key=lambda item: (item["group"], item["label"])),
            "edges": graph_edges,
            "counts": {
                "nodes": len(nodes),
                "edges": len(graph_edges),
                "components": sum(1 for node in nodes.values() if node["group"] == "component"),
                "patterns": sum(1 for node in nodes.values() if node["group"] == "pattern"),
                "semanticEdges": sum(
                    1 for node in nodes.values() if node["group"] == "semantic_edge"
                ),
                "fragments": sum(1 for node in nodes.values() if node["group"] == "fragment"),
            },
        }
        _assert_safe(graph)
        return graph
    finally:
        con.close()


def export_memory_graph_html(
    db_path: str | Path = DEFAULT_DB_PATH,
    output: str | Path = DEFAULT_OUTPUT,
    *,
    planner_visible_only: bool = True,
    limit_patterns: int = 250,
    limit_edges: int = 250,
    limit_fragments: int = 250,
) -> dict[str, Any]:
    graph = build_memory_graph(
        db_path,
        planner_visible_only=planner_visible_only,
        limit_patterns=limit_patterns,
        limit_edges=limit_edges,
        limit_fragments=limit_fragments,
    )
    html_text = _render_html(graph)
    _assert_safe_text(html_text)
    output_path = Path(output)
    output_path.write_text(html_text, encoding="utf-8")
    return {
        "status": "written",
        "output": str(output_path),
        "nodeCount": len(graph["nodes"]),
        "edgeCount": len(graph["edges"]),
        "counts": graph["counts"],
    }


def _add_patterns(
    con: sqlite3.Connection,
    nodes: dict[str, dict[str, Any]],
    graph_edges: list[dict[str, Any]],
    *,
    planner_visible_only: bool,
    limit: int,
) -> None:
    where = (
        "WHERE planner_visible = 1"
        if planner_visible_only and _has_col(con, "research_build_patterns", "planner_visible")
        else ""
    )
    order_by = _order_by(con, "research_build_patterns")
    rows = con.execute(
        f"""
        SELECT pattern_id, pattern_type, title, summary, component_keys, component_roles,
               confidence_tier, sample_count, family_count, source_case_refs, planner_hint,
               verification_tasks, status
        FROM research_build_patterns
        {where}
        {order_by}
        LIMIT ?
        """,
        (max(1, int(limit)),),
    ).fetchall()
    for row in rows:
        pattern_node = f"pattern:{row['pattern_id']}"
        component_keys = _json_list(row["component_keys"])
        component_roles = _json_dict(row["component_roles"])
        _upsert_node(
            nodes,
            {
                "id": pattern_node,
                "label": _safe_text(row["title"], 88),
                "group": "pattern",
                "kind": _safe_text(row["pattern_type"], 40),
                "summary": _safe_text(row["summary"], 420),
                "status": _safe_text(row["status"], 40),
                "confidence": _safe_text(row["confidence_tier"], 60),
                "sampleCount": int(row["sample_count"] or 0),
                "familyCount": int(row["family_count"] or 0),
                "sourceRefs": _json_list(row["source_case_refs"])[:8],
                "plannerHint": _safe_text(row["planner_hint"], 260),
                "verificationTasks": _json_list(row["verification_tasks"])[:5],
            },
        )
        for component_key in component_keys:
            component_node = _component_node(nodes, component_key)
            graph_edges.append(
                {
                    "source": pattern_node,
                    "target": component_node,
                    "type": "uses_component",
                    "label": _safe_text(component_roles.get(component_key, "component"), 60),
                    "weight": max(1, min(8, int(row["sample_count"] or 1))),
                }
            )


def _add_semantic_edges(
    con: sqlite3.Connection,
    nodes: dict[str, dict[str, Any]],
    graph_edges: list[dict[str, Any]],
    *,
    planner_visible_only: bool,
    limit: int,
) -> None:
    where = (
        "WHERE planner_visible = 1"
        if planner_visible_only and _has_col(con, "research_semantic_edges", "planner_visible")
        else ""
    )
    order_by = _order_by(con, "research_semantic_edges")
    rows = con.execute(
        f"""
        SELECT edge_id, source_key, target_key, edge_type, rationale, source_case_refs,
               confidence, status
        FROM research_semantic_edges
        {where}
        {order_by}
        LIMIT ?
        """,
        (max(1, int(limit)),),
    ).fetchall()
    for row in rows:
        source_node = _component_node(nodes, row["source_key"])
        target_node = _component_node(nodes, row["target_key"])
        edge_node = f"semantic_edge:{row['edge_id']}"
        _upsert_node(
            nodes,
            {
                "id": edge_node,
                "label": _safe_text(row["edge_type"], 72),
                "group": "semantic_edge",
                "kind": _safe_text(row["edge_type"], 60),
                "summary": _safe_text(row["rationale"], 420),
                "status": _safe_text(row["status"], 40),
                "confidence": _safe_text(row["confidence"], 60),
                "sourceRefs": _json_list(row["source_case_refs"])[:8],
            },
        )
        graph_edges.append(
            {
                "source": source_node,
                "target": target_node,
                "type": "semantic_source_to_target",
                "label": _safe_text(row["edge_type"], 60),
                "weight": 3,
            }
        )
        graph_edges.append(
            {
                "source": edge_node,
                "target": source_node,
                "type": "edge_source_component",
                "label": "source",
                "weight": 1,
            }
        )
        graph_edges.append(
            {
                "source": edge_node,
                "target": target_node,
                "type": "edge_target_component",
                "label": "target",
                "weight": 1,
            }
        )


def _add_fragments(
    con: sqlite3.Connection,
    nodes: dict[str, dict[str, Any]],
    graph_edges: list[dict[str, Any]],
    *,
    limit: int,
) -> None:
    order_by = _order_by(con, "research_fragments")
    rows = con.execute(
        """
        SELECT fragment_id, fragment_type, title, summary, reusable_principle,
               component_keys, source_case_refs, confidence, status
        FROM research_fragments
        WHERE status IN ('valid', 'needs_revalidation')
        {order_by}
        LIMIT ?
        """.format(order_by=order_by),
        (max(1, int(limit)),),
    ).fetchall()
    for row in rows:
        fragment_node = f"fragment:{row['fragment_id']}"
        _upsert_node(
            nodes,
            {
                "id": fragment_node,
                "label": _safe_text(row["title"], 88),
                "group": "fragment",
                "kind": _safe_text(row["fragment_type"], 60),
                "summary": _safe_text(row["summary"], 360),
                "principle": _safe_text(row["reusable_principle"], 360),
                "status": _safe_text(row["status"], 40),
                "confidence": _safe_text(row["confidence"], 60),
                "sourceRefs": _json_list(row["source_case_refs"])[:8],
            },
        )
        for component_key in _json_list(row["component_keys"]):
            component_node = _component_node(nodes, component_key)
            graph_edges.append(
                {
                    "source": fragment_node,
                    "target": component_node,
                    "type": "mentions_component",
                    "label": "mentions",
                    "weight": 1,
                }
            )


def _component_node(nodes: dict[str, dict[str, Any]], component_key: Any) -> str:
    key = _safe_text(component_key, 160)
    node_id = f"component:{key}"
    prefix = key.split(":", 1)[0] if ":" in key else "component"
    _upsert_node(
        nodes,
        {
            "id": node_id,
            "label": key,
            "group": "component",
            "kind": prefix,
            "summary": key,
            "status": "source_backed_or_referenced",
        },
    )
    return node_id


def _upsert_node(nodes: dict[str, dict[str, Any]], node: dict[str, Any]) -> None:
    existing = nodes.get(node["id"])
    if existing is None:
        nodes[node["id"]] = node
        return
    if existing["group"] == "component":
        return
    existing.update({key: value for key, value in node.items() if value not in ("", [], None)})


def _tables(con: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def _has_col(con: sqlite3.Connection, table: str, column: str) -> bool:
    return any(str(row[1]) == column for row in con.execute(f"PRAGMA table_info({table})"))


def _order_by(con: sqlite3.Connection, table: str) -> str:
    cols = {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}
    order_cols = [col for col in ("last_seen_at", "created_at") if col in cols]
    if not order_cols:
        return ""
    return "ORDER BY " + ", ".join(f"{col} DESC" for col in order_cols)


def _json_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_dict(value: Any) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _safe_text(value: Any, max_len: int = 240) -> str:
    text = " ".join(str(value or "").split())
    text = text[:max_len]
    _assert_safe_text(text)
    return text


def _assert_safe(value: Any) -> None:
    _assert_safe_text(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _assert_safe_text(text: str) -> None:
    lower = text.casefold()
    hits = [marker for marker in RAW_MARKERS if marker.casefold() in lower]
    if hits:
        raise ValueError(f"unsafe graph export marker detected: {', '.join(sorted(set(hits)))}")


def _render_html(graph: dict[str, Any]) -> str:
    graph_json = json.dumps(graph, ensure_ascii=False, sort_keys=True)
    escaped_title = html.escape("Phase 4 Research Memory Graph")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escaped_title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fb;
      --panel: #ffffff;
      --ink: #162033;
      --muted: #66728a;
      --line: #d9deea;
      --accent: #286eea;
      --pattern: #7c3aed;
      --component: #0f9f83;
      --edge: #d97706;
      --fragment: #db2777;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}
    .app {{
      min-height: 100vh;
      display: grid;
      grid-template-columns: minmax(0, 1fr) 360px;
    }}
    header {{
      grid-column: 1 / -1;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 24px;
      padding: 18px 24px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.92);
      backdrop-filter: blur(12px);
    }}
    h1 {{
      margin: 0;
      font-size: 20px;
      line-height: 1.2;
      font-weight: 720;
      letter-spacing: 0;
    }}
    .meta {{
      margin-top: 4px;
      color: var(--muted);
      font-size: 13px;
    }}
    .toolbar {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .search {{
      width: 280px;
      max-width: 42vw;
      height: 36px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0 12px;
      font-size: 14px;
      color: var(--ink);
      background: #fff;
    }}
    .toggle {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 13px;
      color: var(--muted);
      user-select: none;
    }}
    .graph-wrap {{
      min-height: calc(100vh - 74px);
      position: relative;
      overflow: hidden;
    }}
    svg {{
      width: 100%;
      height: calc(100vh - 74px);
      display: block;
      background:
        linear-gradient(#eef2f8 1px, transparent 1px),
        linear-gradient(90deg, #eef2f8 1px, transparent 1px);
      background-size: 28px 28px;
    }}
    aside {{
      min-height: calc(100vh - 74px);
      border-left: 1px solid var(--line);
      background: var(--panel);
      padding: 18px;
      overflow: auto;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 18px;
    }}
    .stat {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fbfcff;
    }}
    .stat strong {{
      display: block;
      font-size: 20px;
      line-height: 1;
    }}
    .stat span {{
      display: block;
      margin-top: 5px;
      color: var(--muted);
      font-size: 12px;
    }}
    .legend {{
      display: grid;
      gap: 8px;
      margin-bottom: 18px;
    }}
    .legend-row {{
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
    }}
    .dot {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
    }}
    .details h2 {{
      margin: 0 0 8px;
      font-size: 18px;
      line-height: 1.25;
      letter-spacing: 0;
    }}
    .details .kind {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 12px;
    }}
    .details p {{
      font-size: 14px;
      line-height: 1.55;
      color: #2b3548;
    }}
    .pill-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin: 10px 0 14px;
    }}
    .pill {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 8px;
      font-size: 12px;
      color: var(--muted);
      background: #fff;
      max-width: 100%;
      overflow-wrap: anywhere;
    }}
    .node-label {{
      pointer-events: none;
      font-size: 11px;
      fill: #233047;
      paint-order: stroke;
      stroke: rgba(255,255,255,0.88);
      stroke-width: 3px;
      stroke-linejoin: round;
    }}
    .edge {{
      stroke: #9aa6bb;
      stroke-opacity: 0.36;
    }}
    .edge.hidden, .node.hidden, .node-label.hidden {{ opacity: 0.06; }}
    .node {{ cursor: pointer; }}
    .node circle {{
      stroke: rgba(255,255,255,0.95);
      stroke-width: 2px;
      filter: drop-shadow(0 3px 8px rgba(34, 45, 70, 0.18));
    }}
    @media (max-width: 900px) {{
      .app {{ grid-template-columns: 1fr; }}
      header {{ align-items: flex-start; flex-direction: column; }}
      .toolbar {{ justify-content: flex-start; }}
      .search {{ max-width: none; width: 100%; }}
      aside {{ min-height: auto; border-left: 0; border-top: 1px solid var(--line); }}
      svg {{ height: 64vh; }}
    }}
  </style>
</head>
<body>
  <div class="app">
    <header>
      <div>
        <h1>Phase 4 Research Memory Graph</h1>
        <div class="meta">安全导出：只展示 durable memory 中的 pattern、component、semantic edge 和 fragment 关系。</div>
      </div>
      <div class="toolbar">
        <input id="search" class="search" placeholder="搜索 skill、pattern、edge、case..." />
        <label class="toggle"><input id="showLabels" type="checkbox" checked /> 标签</label>
      </div>
    </header>
    <main class="graph-wrap">
      <svg id="graph" role="img" aria-label="Phase 4 research memory graph"></svg>
    </main>
    <aside>
      <div class="stats" id="stats"></div>
      <div class="legend">
        <div class="legend-row"><span class="dot" style="background: var(--component)"></span>Component</div>
        <div class="legend-row"><span class="dot" style="background: var(--pattern)"></span>Build Pattern</div>
        <div class="legend-row"><span class="dot" style="background: var(--edge)"></span>Semantic Edge</div>
        <div class="legend-row"><span class="dot" style="background: var(--fragment)"></span>Fragment</div>
      </div>
      <section class="details" id="details">
        <h2>选择一个节点</h2>
        <p>点击图中的点查看摘要、置信度、样本引用和验证任务。拖动节点可以调整布局。</p>
      </section>
    </aside>
  </div>
  <script>
    const GRAPH_DATA = {graph_json};
    const colorByGroup = {{
      component: getCss("--component"),
      pattern: getCss("--pattern"),
      semantic_edge: getCss("--edge"),
      fragment: getCss("--fragment"),
    }};
    const svg = document.getElementById("graph");
    const search = document.getElementById("search");
    const showLabels = document.getElementById("showLabels");
    const details = document.getElementById("details");
    const stats = document.getElementById("stats");
    const nodes = GRAPH_DATA.nodes.map((node, index) => ({{
      ...node,
      x: 120 + (index % 16) * 64,
      y: 100 + Math.floor(index / 16) * 58,
      vx: 0,
      vy: 0,
    }}));
    const nodeById = new Map(nodes.map(node => [node.id, node]));
    const edges = GRAPH_DATA.edges
      .filter(edge => nodeById.has(edge.source) && nodeById.has(edge.target))
      .map(edge => ({{...edge, sourceNode: nodeById.get(edge.source), targetNode: nodeById.get(edge.target)}}));
    let width = 0;
    let height = 0;
    let selectedId = "";
    let dragNode = null;
    let pointerOffset = {{x: 0, y: 0}};
    let dragStart = {{x: 0, y: 0}};
    let hasDragged = false;

    renderStats();
    resize();
    window.addEventListener("resize", resize);
    search.addEventListener("input", render);
    showLabels.addEventListener("change", render);
    svg.addEventListener("pointermove", onPointerMove);
    svg.addEventListener("pointerup", releaseDrag);
    svg.addEventListener("pointerleave", releaseDrag);
    settleLayout();

    function renderStats() {{
      const counts = GRAPH_DATA.counts;
      stats.innerHTML = [
        ["Nodes", counts.nodes],
        ["Edges", counts.edges],
        ["Components", counts.components],
        ["Patterns", counts.patterns],
      ].map(([label, value]) => `<div class="stat"><strong>${{value}}</strong><span>${{label}}</span></div>`).join("");
    }}

    function resize() {{
      const rect = svg.getBoundingClientRect();
      width = Math.max(320, rect.width);
      height = Math.max(360, rect.height);
      settleLayout();
    }}

    function settleLayout(steps = 220) {{
      for (let i = 0; i < steps; i++) {{
        simulate();
      }}
      render();
    }}

    function simulate() {{
      const centerX = width * 0.48;
      const centerY = height * 0.5;
      for (const node of nodes) {{
        if (node === dragNode) continue;
        node.vx += (centerX - node.x) * 0.0007;
        node.vy += (centerY - node.y) * 0.0007;
      }}
      for (const edge of edges) {{
        const a = edge.sourceNode;
        const b = edge.targetNode;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.max(1, Math.hypot(dx, dy));
        const desired = edge.type === "semantic_source_to_target" ? 120 : 86;
        const force = (dist - desired) * 0.0009 * (edge.weight || 1);
        const fx = dx * force;
        const fy = dy * force;
        if (a !== dragNode) {{ a.vx += fx; a.vy += fy; }}
        if (b !== dragNode) {{ b.vx -= fx; b.vy -= fy; }}
      }}
      for (let i = 0; i < nodes.length; i++) {{
        for (let j = i + 1; j < nodes.length; j++) {{
          const a = nodes[i];
          const b = nodes[j];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dist2 = Math.max(36, dx * dx + dy * dy);
          const force = Math.min(1.8, 900 / dist2);
          const dist = Math.sqrt(dist2);
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          if (a !== dragNode) {{ a.vx -= fx; a.vy -= fy; }}
          if (b !== dragNode) {{ b.vx += fx; b.vy += fy; }}
        }}
      }}
      for (const node of nodes) {{
        if (node === dragNode) continue;
        node.vx *= 0.86;
        node.vy *= 0.86;
        node.x = clamp(node.x + node.vx, 30, width - 30);
        node.y = clamp(node.y + node.vy, 30, height - 30);
      }}
    }}

    function render() {{
      const query = search.value.trim().toLowerCase();
      const visible = new Set(nodes.filter(node => matches(node, query)).map(node => node.id));
      const labelDisplay = showLabels.checked ? "" : "hidden";
      const edgeMarkup = edges.map(edge => {{
        const hidden = visible.has(edge.source) && visible.has(edge.target) ? "" : " hidden";
        return `<line class="edge${{hidden}}" x1="${{edge.sourceNode.x.toFixed(1)}}" y1="${{edge.sourceNode.y.toFixed(1)}}" x2="${{edge.targetNode.x.toFixed(1)}}" y2="${{edge.targetNode.y.toFixed(1)}}" stroke-width="${{Math.max(1, Math.min(5, edge.weight || 1))}}" />`;
      }}).join("");
      const nodeMarkup = nodes.map(node => {{
        const hidden = visible.has(node.id) ? "" : " hidden";
        const radius = nodeRadius(node);
        const selected = node.id === selectedId ? 4 : 2;
        return `<g class="node${{hidden}}" data-id="${{escapeAttr(node.id)}}" transform="translate(${{node.x.toFixed(1)}},${{node.y.toFixed(1)}})">
          <circle r="${{radius}}" fill="${{colorByGroup[node.group] || "#64748b"}}" stroke-width="${{selected}}" />
        </g>`;
      }}).join("");
      const labels = nodes.map(node => {{
        const hidden = visible.has(node.id) ? "" : " hidden";
        return `<text class="node-label ${{labelDisplay}}${{hidden}}" x="${{(node.x + nodeRadius(node) + 5).toFixed(1)}}" y="${{(node.y + 4).toFixed(1)}}">${{escapeHtml(shortLabel(node.label))}}</text>`;
      }}).join("");
      svg.innerHTML = edgeMarkup + nodeMarkup + labels;
      svg.querySelectorAll(".node").forEach(el => {{
        el.addEventListener("pointerdown", event => {{
          const node = nodeById.get(el.dataset.id);
          selectedId = node.id;
          showDetails(node);
          dragNode = node;
          const point = pointer(event);
          dragStart = point;
          hasDragged = false;
          pointerOffset = {{x: node.x - point.x, y: node.y - point.y}};
          el.setPointerCapture(event.pointerId);
          render();
        }});
      }});
    }}

    function showDetails(node) {{
      const refs = (node.sourceRefs || []).map(ref => `<span class="pill">${{escapeHtml(ref)}}</span>`).join("");
      const tasks = (node.verificationTasks || []).map(task => `<span class="pill">${{escapeHtml(task)}}</span>`).join("");
      details.innerHTML = `
        <h2>${{escapeHtml(node.label)}}</h2>
        <div class="kind">${{escapeHtml(node.group)}} · ${{escapeHtml(node.kind || "")}} · ${{escapeHtml(node.status || "")}}</div>
        <div class="pill-row">
          ${{node.confidence ? `<span class="pill">confidence: ${{escapeHtml(node.confidence)}}</span>` : ""}}
          ${{node.sampleCount ? `<span class="pill">samples: ${{node.sampleCount}}</span>` : ""}}
          ${{node.familyCount ? `<span class="pill">families: ${{node.familyCount}}</span>` : ""}}
        </div>
        <p>${{escapeHtml(node.summary || node.principle || "No summary.")}}</p>
        ${{node.plannerHint ? `<p><strong>Planner hint:</strong> ${{escapeHtml(node.plannerHint)}}</p>` : ""}}
        ${{refs ? `<h2>Source refs</h2><div class="pill-row">${{refs}}</div>` : ""}}
        ${{tasks ? `<h2>Verification</h2><div class="pill-row">${{tasks}}</div>` : ""}}
      `;
    }}

    function matches(node, query) {{
      if (!query) return true;
      return JSON.stringify(node).toLowerCase().includes(query);
    }}

    function nodeRadius(node) {{
      if (node.group === "component") return 8;
      if (node.group === "semantic_edge") return 7;
      if (node.group === "fragment") return 9;
      return Math.max(10, Math.min(18, 9 + (node.sampleCount || 1)));
    }}

    function onPointerMove(event) {{
      if (!dragNode) return;
      const point = pointer(event);
      const movement = Math.hypot(point.x - dragStart.x, point.y - dragStart.y);
      if (!hasDragged) {{
        hasDragged = movement > 4;
      }}
      if (!hasDragged) {{
        return;
      }}
      dragNode.x = clamp(point.x + pointerOffset.x, 30, width - 30);
      dragNode.y = clamp(point.y + pointerOffset.y, 30, height - 30);
      dragNode.vx = 0;
      dragNode.vy = 0;
      render();
    }}

    function releaseDrag() {{
      if (!dragNode) return;
      dragNode = null;
      if (hasDragged) {{
        settleLayout(45);
      }}
    }}

    function pointer(event) {{
      const rect = svg.getBoundingClientRect();
      return {{x: event.clientX - rect.left, y: event.clientY - rect.top}};
    }}

    function shortLabel(label) {{
      return label.length > 34 ? label.slice(0, 31) + "..." : label;
    }}

    function escapeHtml(value) {{
      return String(value || "").replace(/[&<>"']/g, ch => ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}}[ch]));
    }}

    function escapeAttr(value) {{
      return escapeHtml(value).replace(/`/g, "&#96;");
    }}

    function clamp(value, min, max) {{
      return Math.max(min, Math.min(max, value));
    }}

    function getCss(name) {{
      return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }}
  </script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--include-hidden", action="store_true")
    parser.add_argument("--limit-patterns", type=int, default=250)
    parser.add_argument("--limit-edges", type=int, default=250)
    parser.add_argument("--limit-fragments", type=int, default=250)
    args = parser.parse_args(argv)

    report = export_memory_graph_html(
        args.db_path,
        args.output,
        planner_visible_only=not args.include_hidden,
        limit_patterns=args.limit_patterns,
        limit_edges=args.limit_edges,
        limit_fragments=args.limit_fragments,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
