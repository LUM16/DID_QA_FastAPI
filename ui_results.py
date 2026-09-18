"""Insight2-style result visuals: labeled charts, org chart, force graph."""

from __future__ import annotations

import json
from html import escape
from typing import Any

PIE_COLORS = [
    "#4f8cff",
    "#37d0a0",
    "#f5b945",
    "#ff6b6b",
    "#9b7bff",
    "#3fd0e0",
    "#e08fdc",
    "#8bd36b",
    "#f08d5a",
    "#6ea8ff",
]


def cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        if value and all(isinstance(item, dict) and item.get("_relationship") for item in value):
            return f"{len(value)} × {value[0].get('_relationship')}"
        if value and all(
            isinstance(item, dict) and ("Name" in item or "title" in item) for item in value
        ):
            return ", ".join(str(item.get("Name") or item.get("title") or "") for item in value)
        return "; ".join(cell_text(item) for item in value)
    if isinstance(value, dict):
        for key in ("Name", "title", "DID"):
            if value.get(key):
                return str(value[key])
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _find_column(columns: list[str], names: list[str], pattern: str | None = None) -> str | None:
    lowered = {str(col).lower(): col for col in columns}
    for name in names:
        if name in lowered:
            return lowered[name]
    if pattern:
        import re

        rx = re.compile(pattern, re.IGNORECASE)
        for col in columns:
            if rx.search(str(col)):
                return col
    return None


def org_from_rows(rows: list[dict[str, Any]], columns: list[str] | None = None) -> dict[str, Any] | None:
    """Build a synthetic org graph from scalar reporting rows."""
    if not rows:
        return None
    cols = columns or list(dict.fromkeys(key for row in rows for key in row))
    person_col = _find_column(cols, ["person", "name", "employee", "member", "direct_report"])
    reports_col = _find_column(cols, ["reports_to", "reportsto", "manager", "managers"])
    status_col = _find_column(cols, ["status"])
    if not person_col or not reports_col:
        return None

    node_map: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []

    def ensure(name: Any, status: str = "") -> str | None:
        text = cell_text(name).strip()
        if not text:
            return None
        if text not in node_map:
            node_map[text] = {
                "id": text,
                "label": "Person",
                "labels": ["Person"],
                "title": text,
                "properties": {"Name": text, "Status": status or ""},
            }
        elif status and not node_map[text]["properties"].get("Status"):
            node_map[text]["properties"]["Status"] = status
        return text

    def as_list(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [value.get("Name") or value.get("title") or ""]
        text = str(value).strip()
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, list) else [parsed]
        except (TypeError, ValueError, json.JSONDecodeError):
            return [part for part in text.replace(";", ",").split(",") if part.strip()]

    for row in rows:
        employee = ensure(row.get(person_col), str(row.get(status_col) or "") if status_col else "")
        if not employee:
            continue
        for manager in as_list(row.get(reports_col)):
            manager_name = ensure(manager if not isinstance(manager, dict) else cell_text(manager))
            if manager_name and manager_name != employee:
                edges.append({"source": employee, "target": manager_name, "type": "REPORTS_TO"})

    nodes = list(node_map.values())
    if len(nodes) < 2 or not edges:
        return None
    return {
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "synthetic": True,
    }


def is_org_graph(graph: dict[str, Any] | None) -> bool:
    if not graph or not graph.get("edges"):
        return False
    edges = graph["edges"]
    nodes = graph.get("nodes") or []
    if not edges or not nodes:
        return False
    reports = sum(1 for edge in edges if edge.get("type") == "REPORTS_TO") / len(edges)
    people = sum(
        1
        for node in nodes
        if node.get("label") == "Person" or "Person" in (node.get("labels") or [])
    ) / max(1, len(nodes))
    return reports >= 0.8 and people >= 0.8


def build_org_html(graph: dict[str, Any]) -> str:
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    by_id = {node["id"]: node for node in nodes}
    children: dict[str, list[str]] = {}
    has_boss: set[str] = set()
    mgr_of: dict[str, str] = {}
    for edge in edges:
        manager, child = edge.get("target"), edge.get("source")
        if manager not in by_id or child not in by_id:
            continue
        children.setdefault(manager, []).append(child)
        has_boss.add(child)
        mgr_of[child] = manager

    roots = [node for node in nodes if node["id"] not in has_boss]
    root = roots[0] if roots else None
    if len(roots) > 1:
        root = max(roots, key=lambda node: len(children.get(node["id"], [])))

    levels: list[list[str]] = []
    seen: set[str] = set()
    frontier = [root["id"]] if root else []
    while frontier:
        levels.append(frontier)
        nxt: list[str] = []
        for node_id in frontier:
            seen.add(node_id)
            for child in children.get(node_id, []):
                if child not in seen:
                    nxt.append(child)
        frontier = sorted(
            set(nxt),
            key=lambda nid: str((by_id.get(nid) or {}).get("properties", {}).get("Name") or ""),
        )
    rest = [node["id"] for node in nodes if node["id"] not in seen]
    if rest:
        levels.append(rest)

    def name_of(node_id: str) -> str:
        node = by_id.get(node_id) or {}
        props = node.get("properties") or {}
        return str(props.get("Name") or node.get("title") or node.get("label") or node_id)

    def card(node_id: str) -> str:
        node = by_id.get(node_id) or {}
        props = node.get("properties") or {}
        roles = []
        if props.get("Group_Lead") == "Y":
            roles.append("Group Lead")
        if props.get("TA_Lead") == "Y":
            roles.append("TA Lead")
        if props.get("Manager") == "Y":
            roles.append("Manager")
        status = props.get("Status")
        st = "Active" if status == "Active" else ("Inactive" if status == "Inactive" else "Other")
        manager = mgr_of.get(node_id)
        role_html = "".join(f'<span class="role">{escape(role)}</span>' for role in roles)
        site = escape(str(props.get("Site") or ""))
        inactive = " · Inactive" if status == "Inactive" else ""
        reports = (
            f'<div class="meta">Reports to {escape(name_of(manager))}</div>' if manager else ""
        )
        return (
            f'<div class="ocard"><div class="nm"><span class="st {st}"></span>'
            f"{escape(name_of(node_id))}</div>"
            f'<div class="meta">{role_html}{site}{inactive}</div>{reports}</div>'
        )

    cols_html = []
    for index, ids in enumerate(levels):
        cards = "".join(card(node_id) for node_id in ids)
        cols_html.append(
            f'<div class="org-col"><h4>Level {index} · {len(ids)}</h4>{cards}</div>'
        )
    note = (
        f"By reporting level (Level 0 = self/top): {graph.get('node_count', len(nodes))} "
        f"people across {len(levels)} level(s)"
    )
    if graph.get("truncated_graph"):
        note += " (large graph truncated)"
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<style>
  body{{margin:0;font-family:"Segoe UI",system-ui,sans-serif;background:#fff;color:#1b2435;font-size:13px}}
  .org{{overflow:auto;border:1px solid #d6ddea;border-radius:8px;background:#fff;padding:10px}}
  .org-cols{{display:flex;gap:14px;min-width:max-content;align-items:flex-start}}
  .org-col{{display:flex;flex-direction:column;gap:8px;min-width:196px;max-width:220px}}
  .org-col h4{{position:sticky;top:0;background:#fff;margin:0 0 2px;padding:4px 0 6px;
              border-bottom:1px solid #d6ddea;font-size:12px;color:#5c6a86}}
  .ocard{{border:1px solid #d6ddea;border-radius:8px;padding:7px 9px;background:#f2f5fb;font-size:12px}}
  .ocard .nm{{font-weight:600;line-height:1.3}}
  .meta{{color:#5c6a86;font-size:11px;margin-top:3px}}
  .role{{display:inline-block;font-size:10px;border:1px solid #0ca678;color:#0ca678;
        border-radius:999px;padding:0 6px;margin:2px 4px 0 0}}
  .st{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}}
  .st.Active{{background:#0ca678}} .st.Inactive{{background:#e04141}} .st.Other{{background:#5c6a86}}
  .muted{{color:#5c6a86;font-size:12px;margin-bottom:8px}}
</style></head><body>
<div class="org"><div class="muted">{escape(note)}</div>
<div class="org-cols">{''.join(cols_html)}</div></div>
</body></html>"""


def org_component_height(graph: dict[str, Any]) -> int:
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    children: dict[str, list[str]] = {}
    for edge in edges:
        children.setdefault(edge.get("target"), []).append(edge.get("source"))
    fanout = max((len(v) for v in children.values()), default=1)
    max_in_level = max(fanout, max(1, (len(nodes) + 3) // 4)) if nodes else 1
    return min(720, max(280, 90 + max_in_level * 78))


def numeric(value: Any) -> float | None:
    try:
        number = float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # NaN check


def chart_payload(visualization: dict[str, Any]) -> tuple[str, list[str], list[float]] | None:
    """Return (kind, labels, values) for Insight2 canvas charts (single series)."""
    if not visualization:
        return None
    display = visualization.get("display_type") or visualization.get("chart_type")
    data = visualization.get("data") or []
    if display in {"stacked_bar", "grouped_bar"} or visualization.get("series"):
        return None
    if display == "pie":
        names = visualization.get("names") or visualization.get("x")
        values = visualization.get("values") or (
            visualization.get("y")[0]
            if isinstance(visualization.get("y"), list)
            else visualization.get("y")
        )
        if not names or not values:
            return None
        rows = data[:20]
        return (
            "pie",
            [cell_text(row.get(names)) for row in rows],
            [numeric(row.get(values)) or 0 for row in rows],
        )
    if display not in {"bar", "horizontal_bar", "line"} and visualization.get("chart_type") not in {
        "bar",
        "line",
        "monthly_hours_chart",
        "did_effort_distribution_chart",
    }:
        return None
    x_field = visualization.get("x")
    y_field = visualization.get("y")
    if visualization.get("chart_type") == "monthly_hours_chart":
        x_field, y_field = "month", "hours"
        display = "bar"
    elif visualization.get("chart_type") == "did_effort_distribution_chart":
        x_field = "person"
        y_field = visualization.get("value_field", "hours")
        display = "horizontal_bar"
    if isinstance(y_field, list):
        if len(y_field) != 1:
            return None
        y_field = y_field[0]
    if not x_field or not y_field or not data:
        return None
    rows = data[:20]
    labels = [cell_text(row.get(x_field)) for row in rows]
    values = [numeric(row.get(y_field)) or 0 for row in rows]
    kind = "line" if display == "line" or visualization.get("chart_type") == "line" else "bar"
    if display == "horizontal_bar" or (
        kind == "bar" and any(len(str(label or "")) > 12 for label in labels)
    ):
        kind = "hbar"
    return kind, labels, values


def chart_html(kind: str, labels: list[str], values: list[float], title: str = "") -> str:
    payload = json.dumps(
        {"kind": kind, "labels": labels, "values": values, "title": title},
        ensure_ascii=False,
    )
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<style>
  :root {{
    --c-grid:#e7ebf3; --c-axis:#7c89a3; --c-axisline:#c7d0e0;
    --c-bar:#2f6bf0; --c-line:#0ca678; --c-gtext:#46536d; --c-onbar:#ffffff;
    --c-piestroke:#ffffff; --chart-val:#1b2435; --chart-cat:#51607c;
    --tip-bg:#ffffff; --tip-border:#c3ccdd; --tip-text:#1b2435;
  }}
  body{{margin:0;background:#fff;font-family:"Segoe UI",system-ui,sans-serif}}
  canvas{{width:100%;height:auto;display:block;background:#fff;border:1px solid #d6ddea;border-radius:8px}}
  .wrap{{position:relative}}
  .title{{font-size:12px;color:#5c6a86;margin:0 0 6px}}
  .chart-tip{{display:none;position:absolute;z-index:30;pointer-events:none;max-width:300px;
    background:var(--tip-bg);border:1px solid var(--tip-border);border-radius:6px;padding:5px 9px;font-size:12px;
    color:var(--tip-text);box-shadow:0 6px 20px rgba(0,0,0,.12);white-space:normal}}
</style></head><body>
<div class="wrap" id="pane">{'<div class="title"></div>' if title else ''}<canvas id="cv"></canvas></div>
<script>
const DATA = {payload};
const PIE_COLORS = {json.dumps(PIE_COLORS)};
const pane = document.getElementById('pane');
const cv = document.getElementById('cv');
const titleEl = pane.querySelector('.title');
if (titleEl) titleEl.textContent = DATA.title || '';
function cssVar(n){{return getComputedStyle(document.documentElement).getPropertyValue(n).trim();}}
function pal(){{return {{grid:cssVar('--c-grid'),axis:cssVar('--c-axis'),axisLine:cssVar('--c-axisline'),
  bar:cssVar('--c-bar'),line:cssVar('--c-line'),gtext:cssVar('--c-gtext'),onbar:cssVar('--c-onbar'),
  piestroke:cssVar('--c-piestroke'),val:cssVar('--chart-val'),cat:cssVar('--chart-cat')}};}}
function esc(s){{return String(s??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));}}
function fmt(v){{
  const n=Number(v); if(!isFinite(n)) return String(v??'');
  const a=Math.abs(n);
  if(a>=1000000) return (n/1000000).toFixed(a>=10000000?0:1)+'M';
  if(a>=1000) return n.toLocaleString(undefined,{{maximumFractionDigits:1}});
  return Number.isInteger(n)?String(n):n.toFixed(1);
}}
function niceMax(mx){{ if(!(mx>0)) return 1;
  const pow=Math.pow(10,Math.floor(Math.log10(mx))), k=mx/pow;
  const f=(k<=1)?1:(k<=2)?2:(k<=2.5)?2.5:(k<=5)?5:10; return f*pow; }}
function fitText(ctx,t,maxw){{ t=String(t??'');
  if(ctx.measureText(t).width<=maxw) return t;
  while(t.length>1 && ctx.measureText(t+'…').width>maxw) t=t.slice(0,-1);
  return t+'…'; }}
function initCanvas(W,H,dpr){{ cv.width=W*dpr; cv.height=H*dpr; cv.style.width='100%';
  const ctx=cv.getContext('2d'); ctx.setTransform(dpr,0,0,dpr,0,0); ctx.clearRect(0,0,W,H); return ctx; }}
function bindHover(W,H,hits){{
  let tip=pane.querySelector('.chart-tip');
  if(!tip){{tip=document.createElement('div');tip.className='chart-tip';pane.appendChild(tip);}}
  cv.onmousemove=e=>{{ const rect=cv.getBoundingClientRect();
    const mx=(e.clientX-rect.left)/rect.width*W, my=(e.clientY-rect.top)/rect.height*H;
    const h=hits.find(z=>z.test?z.test(mx,my):(mx>=z.x&&mx<=z.x+z.w&&my>=z.y&&my<=z.y+z.h));
    if(h){{ tip.style.display='block'; tip.innerHTML=`${{esc(h.label)}}<br><b>${{fmt(h.value)}}</b>`;
      const pr=pane.getBoundingClientRect();
      let x=e.clientX-pr.left+14, y=e.clientY-pr.top+14;
      if(x+tip.offsetWidth>pr.width-4) x=e.clientX-pr.left-tip.offsetWidth-10;
      tip.style.left=Math.max(0,x)+'px'; tip.style.top=Math.max(0,y)+'px'; cv.style.cursor='default';
    }} else tip.style.display='none';
  }};
  cv.onmouseleave=()=>{{tip.style.display='none';}};
}}
function vChart(labels,vals,isLine){{
  const W=900,H=380,padL=56,padR=24,top=24,padB=74,dpr=window.devicePixelRatio||1;
  const ctx=initCanvas(W,H,dpr); const P=pal();
  const x0=padL,x1=W-padR,y0=top,y1=H-padB,pw=x1-x0,ph=y1-y0;
  const max=niceMax(Math.max(...vals,0)), ticks=5;
  ctx.font='10px sans-serif';
  for(let t=0;t<=ticks;t++){{const val=max*t/ticks,y=y1-ph*t/ticks;
    ctx.strokeStyle=P.grid;ctx.beginPath();ctx.moveTo(x0,y);ctx.lineTo(x1,y);ctx.stroke();
    ctx.fillStyle=P.axis;ctx.textAlign='right';ctx.textBaseline='middle';ctx.fillText(fmt(val),x0-7,y);}}
  ctx.strokeStyle=P.axisLine;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x0,y0);ctx.lineTo(x0,y1);ctx.lineTo(x1,y1);ctx.stroke();
  const n=vals.length,slot=pw/n,barW=Math.min(46,slot*0.62),hits=[];
  const cx=i=>x0+slot*(i+0.5), yy=v=>y1-ph*(v/max);
  if(isLine){{ctx.strokeStyle=P.line;ctx.lineWidth=2;ctx.beginPath();
    vals.forEach((v,i)=>{{const X=cx(i),Y=yy(v); i?ctx.lineTo(X,Y):ctx.moveTo(X,Y);}});ctx.stroke();ctx.lineWidth=1;}}
  vals.forEach((v,i)=>{{const X=cx(i),Y=yy(v);
    if(isLine){{ctx.fillStyle=P.line;ctx.beginPath();ctx.arc(X,Y,3.2,0,7);ctx.fill();
      if(n<=12){{ctx.fillStyle=P.val;ctx.font='11px sans-serif';ctx.textAlign='center';ctx.textBaseline='bottom';ctx.fillText(fmt(v),X,Y-7);}}
      hits.push({{x:X-12,y:y0,w:24,h:y1-y0+16,label:labels[i],value:v}});
    }}else{{const w=barW;ctx.fillStyle=P.bar;ctx.fillRect(X-w/2,Y,w,y1-Y);
      ctx.fillStyle=P.val;ctx.font='11px sans-serif';ctx.textAlign='center';ctx.textBaseline='bottom';
      ctx.fillText(fmt(v),X,Y-4);
      hits.push({{x:X-w/2,y:y0,w:w,h:y1-y0,label:labels[i],value:v}});}}
    ctx.save();ctx.translate(X,y1+9);ctx.rotate(-0.55);
    ctx.fillStyle=P.cat;ctx.font='10.5px sans-serif';ctx.textAlign='right';ctx.textBaseline='middle';
    ctx.fillText(fitText(ctx,String(labels[i]??''),84),0,0);ctx.restore();
  }});
  bindHover(W,H,hits);
}}
function hBar(labels,vals){{
  const W=900,n=vals.length,rowH=n<=12?30:26,top=14,bottom=30,dpr=window.devicePixelRatio||1;
  const H=Math.max(380,top+n*rowH+bottom);
  const ctx=initCanvas(W,H,dpr); const P=pal();
  ctx.font='11.5px sans-serif';
  const shortName=l=>{{const t=String(l??'');return t.length>26?t.slice(0,25)+'…':t;}};
  let nameW=0;labels.forEach(l=>{{nameW=Math.max(nameW,ctx.measureText(shortName(l)).width);}});
  nameW=Math.min(210,nameW);
  const x0=nameW+14,x1=W-66,pw=x1-x0,max=niceMax(Math.max(...vals,0)),ticks=4,plotTop=top,plotH=n*rowH;
  ctx.font='10px sans-serif';
  for(let t=0;t<=ticks;t++){{const val=max*t/ticks,x=x0+pw*t/ticks;
    ctx.strokeStyle=P.grid;ctx.beginPath();ctx.moveTo(x,plotTop);ctx.lineTo(x,plotTop+plotH);ctx.stroke();
    ctx.fillStyle=P.axis;ctx.textAlign='center';ctx.textBaseline='top';ctx.fillText(fmt(val),x,plotTop+plotH+6);}}
  ctx.strokeStyle=P.axisLine;ctx.beginPath();ctx.moveTo(x0,plotTop);ctx.lineTo(x0,plotTop+plotH);ctx.stroke();
  const hits=[];
  vals.forEach((v,i)=>{{const cy=plotTop+i*rowH+rowH/2,bh=Math.min(18,rowH*0.56),w=pw*(v/max);
    ctx.fillStyle=P.cat;ctx.font='11.5px sans-serif';ctx.textAlign='right';ctx.textBaseline='middle';
    ctx.fillText(fitText(ctx,String(labels[i]??''),nameW),x0-9,cy);
    ctx.fillStyle=P.bar;ctx.fillRect(x0,cy-bh/2,Math.max(w,v?2:0),bh);
    ctx.font='bold 11.5px sans-serif';
    if(w>pw-54){{ctx.fillStyle=P.onbar;ctx.textAlign='right';ctx.fillText(fmt(v),x0+w-7,cy);}}
    else{{ctx.fillStyle=P.val;ctx.textAlign='left';ctx.fillText(fmt(v),x0+w+7,cy);}}
    hits.push({{x:x0,y:cy-bh/2,w:pw,h:bh,label:labels[i],value:v}});
  }});
  bindHover(W,H,hits);
}}
function pieChart(labels,vals){{
  const n=vals.length,W=900,H=Math.max(380,44+n*24),dpr=window.devicePixelRatio||1;
  const ctx=initCanvas(W,H,dpr); const P=pal();
  const val0=i=>isFinite(vals[i])&&vals[i]>0?vals[i]:0;
  const total=vals.reduce((a,b)=>a+(isFinite(b)&&b>0?b:0),0)||1;
  const cx=W*0.27,cy=H/2,r=Math.min(150,H/2-28);
  let a=-Math.PI/2; const hits=[];
  vals.forEach((v,i)=>{{const frac=val0(i)/total,ang=frac*Math.PI*2,a0=a,a1=a+ang;
    ctx.beginPath();ctx.moveTo(cx,cy);ctx.arc(cx,cy,r,a,a+ang);ctx.closePath();
    ctx.fillStyle=PIE_COLORS[i%PIE_COLORS.length];ctx.fill();
    ctx.strokeStyle=P.piestroke;ctx.lineWidth=1.5;ctx.stroke();
    if(frac>=0.06){{const mid=a+ang/2,px=cx+Math.cos(mid)*r*0.62,py=cy+Math.sin(mid)*r*0.62;
      ctx.fillStyle='#fff';ctx.font='bold 11px sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';
      ctx.fillText((frac*100).toFixed(frac>=0.2?0:1)+'%',px,py);}}
    hits.push({{label:labels[i],value:v,test:(mx,my)=>{{const dx=mx-cx,dy=my-cy;if(Math.hypot(dx,dy)>r)return false;
      let th=Math.atan2(dy,dx);while(th<a0)th+=2*Math.PI;return th>=a0&&th<=a1;}}}});
    a+=ang;}});
  const lx=cx+r+44;ctx.font='12px sans-serif';ctx.textBaseline='middle';
  vals.forEach((v,i)=>{{const y=30+i*24;
    ctx.fillStyle=PIE_COLORS[i%PIE_COLORS.length];ctx.fillRect(lx,y-7,12,12);
    ctx.fillStyle=P.cat;ctx.textAlign='left';
    const pct=val0(i)/total*100;
    ctx.fillText(`${{fitText(ctx,String(labels[i]??''),W-lx-24)}} — ${{fmt(v)}} (${{pct.toFixed(1)}}%)`,lx+18,y);}});
  bindHover(W,H,hits);
}}
const kind=DATA.kind, labels=DATA.labels||[], vals=(DATA.values||[]).map(v=>Number(v)||0);
if(kind==='pie') pieChart(labels,vals);
else if(kind==='line') vChart(labels,vals,true);
else if(kind==='hbar') hBar(labels,vals);
else vChart(labels,vals,false);
</script></body></html>"""


def chart_component_height(kind: str, n: int) -> int:
    if kind == "hbar":
        return min(720, max(400, 14 + n * 30 + 40))
    if kind == "pie":
        return min(640, max(400, 44 + n * 24 + 20))
    return 420


def graph_html(graph: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "nodes": (graph.get("nodes") or [])[:160],
            "edges": graph.get("edges") or [],
        },
        ensure_ascii=False,
        default=str,
    )
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<style>
  body{{margin:0;background:#fff}}
  canvas{{width:100%;height:auto;display:block;background:#fff;border:1px solid #d6ddea;border-radius:8px}}
</style></head><body><canvas id="cv"></canvas>
<script>
const g = {payload};
const cv=document.getElementById('cv'); cv.width=940; cv.height=520;
const nodes=(g.nodes||[]).map((n,i)=>({{x:470+Math.cos(i)*220+(Math.random()*40),y:260+Math.sin(i)*220+(Math.random()*40),vx:0,vy:0,d:n}}));
const id=new Map(nodes.map(n=>[n.d.id,n]));
const edges=(g.edges||[]).filter(e=>id.has(e.source)&&id.has(e.target)).map(e=>({{s:id.get(e.source),t:id.get(e.target),type:e.type}}));
const ctx=cv.getContext('2d');
for(let k=0;k<260;k++){{
  for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){{
    const a=nodes[i],b=nodes[j];let dx=a.x-b.x,dy=a.y-b.y;let d2=dx*dx+dy*dy||1;const f=9000/d2;
    const d=Math.sqrt(d2);dx/=d;dy/=d;a.vx+=dx*f;a.vy+=dy*f;b.vx-=dx*f;b.vy-=dy*f;}}
  edges.forEach(e=>{{let dx=e.t.x-e.s.x,dy=e.t.y-e.s.y;const d=Math.hypot(dx,dy)||1;const f=(d-110)*0.01;
    dx/=d;dy/=d;e.s.vx+=dx*f;e.s.vy+=dy*f;e.t.vx-=dx*f;e.t.vy-=dy*f;}});
  nodes.forEach(n=>{{n.vx+=(470-n.x)*0.002;n.vy+=(260-n.y)*0.002;n.vx*=0.85;n.vy*=0.85;n.x+=n.vx;n.y+=n.vy;}});
}}
ctx.strokeStyle='#c2cbdd';ctx.lineWidth=1;
edges.forEach(e=>{{ctx.beginPath();ctx.moveTo(e.s.x,e.s.y);ctx.lineTo(e.t.x,e.t.y);ctx.stroke();}});
nodes.forEach(n=>{{ctx.fillStyle='#2f6bf0';ctx.beginPath();ctx.arc(n.x,n.y,6,0,7);ctx.fill();
  ctx.fillStyle='#46536d';ctx.font='10px sans-serif';ctx.fillText(String(n.d.title||n.d.label||'').slice(0,22),n.x+8,n.y+3);}});
</script></body></html>"""
