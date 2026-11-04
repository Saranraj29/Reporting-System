"""Turns the small subset of mermaid that our markdown reports emit (pie charts and linear `flowchart LR` chains) into inline SVG /
HTML, so the on-screen report, the PDF and the shared page show real charts without loading any script. The raw markdown keeps
the ```mermaid blocks for GitHub / GitLab / VS Code. Anything else is shown as a plain code block."""

import html
import math
import re

PALETTE = ["#3b5bdb", "#0ca678", "#f59f00", "#e8590c", "#7048e8", "#1098ad", "#d6336c", "#868e96", "#2f9e44", "#e03131"]


def _pie(src: str) -> str | None:
    title = ""
    items: list[tuple[str, float]] = []
    for line in src.splitlines():
        line = line.strip()
        m = re.match(r"^pie(?:\s+showData)?(?:\s+title\s+(.*))?$", line)
        if m:
            title = (m.group(1) or "").strip()
            continue
        m = re.match(r'^"(.+?)"\s*:\s*([0-9.]+)$', line)
        if m:
            items.append((m.group(1), float(m.group(2))))
    items = [(k, v) for k, v in items if v > 0]
    total = sum(v for _, v in items)
    if not items or not total:
        return None
    cx = cy = 90
    r = 80
    parts, angle = [], -math.pi / 2
    for i, (_, v) in enumerate(items):
        color = PALETTE[i % len(PALETTE)]
        if len(items) == 1:
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}"/>')
            break
        sweep = v / total * 2 * math.pi
        x1, y1 = cx + r * math.cos(angle), cy + r * math.sin(angle)
        x2, y2 = cx + r * math.cos(angle + sweep), cy + r * math.sin(angle + sweep)
        parts.append(f'<path d="M{cx},{cy} L{x1:.2f},{y1:.2f} A{r},{r} 0 {1 if sweep > math.pi else 0} 1 {x2:.2f},{y2:.2f} Z" fill="{color}" stroke="#fff" stroke-width="2"/>')
        angle += sweep
    legend = "".join(
        f'<li><span class="sw" style="background:{PALETTE[i % len(PALETTE)]}"></span>{html.escape(k)} <b>{v:g}</b> <small>({v / total * 100:.0f}%)</small></li>'
        for i, (k, v) in enumerate(items)
    )
    cap = f"<figcaption>{html.escape(title)}</figcaption>" if title else ""
    return f'<figure class="chart pie">{cap}<div class="row"><svg viewBox="0 0 180 180" width="180" height="180" role="img" aria-label="{html.escape(title)}">{"".join(parts)}</svg><ul>{legend}</ul></div></figure>'


def _flow(src: str) -> str | None:
    if not src.strip().startswith("flowchart"):
        return None
    labels: dict[str, str] = {}
    order: list[str] = []
    for node_id, text in re.findall(r"([A-Za-z0-9_]+)\[([^\]]*)\]", src):
        if node_id not in labels:
            order.append(node_id)
        labels[node_id] = text
    if not order:
        return None
    boxes = '<span class="arrow">→</span>'.join(f'<span class="node">{html.escape(labels[n])}</span>' for n in order)
    return f'<div class="chart flow">{boxes}</div>'


def to_html(kind_src: str) -> str | None:
    src = kind_src.strip()
    if src.startswith("pie"):
        return _pie(src)
    if src.startswith("flowchart") or src.startswith("graph"):
        return _flow(src)
    return None


_BLOCK = re.compile(r'<pre><code class="language-mermaid">(.*?)</code></pre>', re.S)


def replace_blocks(rendered_html: str) -> str:
    def sub(m: re.Match) -> str:
        converted = to_html(html.unescape(m.group(1)))
        return converted if converted is not None else m.group(0)

    return _BLOCK.sub(sub, rendered_html)
