"""Export the live, compiled LangGraph topology locally. No model call is made."""

import argparse
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from travel_app.graph import Workflow


LABELS = {"__start__": "시작", "__end__": "실행 반환", "resume": "저장 단계 복구",
          "team": "생성자 · 역할 배정", "propose": "제안 작성", "judge": "결정자 · 중재",
          "open": "파이트 모드 열기", "floor": "발언 순서·마감", "speak": "개인 발언",
          "final": "결과 확정", "personal_agent": "참가자별 에이전트",
          "interpret": "개인 조건 해석", "search": "외부 근거 검색"}


def element(parent, tag, attrs=None, text=None):
    child = ET.SubElement(parent, tag, {k: str(v) for k, v in (attrs or {}).items()})
    if text is not None:
        child.text = text
    return child


def text(parent, x, y, content, size=15, weight=400, color="#222725", anchor="start"):
    return element(parent, "text", {"x": x, "y": y, "font-size": size, "font-weight": weight,
                                    "fill": color, "text-anchor": anchor}, content)


def rect(parent, x, y, w, h, *, fill="white", stroke="#d4d8d5", radius=12):
    return element(parent, "rect", {"x": x, "y": y, "width": w, "height": h, "rx": radius,
                                    "fill": fill, "stroke": stroke})


def spine(nodes, edges):
    adjacent = defaultdict(list)
    incoming = set()
    for e in edges:
        if e.source != e.target:
            adjacent[e.source].append(e.target)
            incoming.add(e.target)
    starts = sorted(set(nodes) - incoming) or sorted(nodes)
    best = []

    def visit(path):
        nonlocal best
        if len(path) > len(best):
            best = path
        for dest in sorted(adjacent[path[-1]]):
            if dest not in path:
                visit([*path, dest])
    for start in starts:
        visit([start])
    return best


def draw_graph(root, graph_name, nodes, edges, x, width, heading, description):
    group = element(root, "g", {"data-graph": graph_name})
    rect(group, x, 122, width, 482)
    text(group, x + 20, 155, heading, 20, 700)
    text(group, x + 20, 181, description, 13, color="#526059")
    order = spine(nodes, edges)
    spare = sorted(set(nodes) - set(order))
    center = x + (width * .34 if spare else width / 2)
    positions = {name: (center, 227 + i * 64) for i, name in enumerate(order)}
    for i, name in enumerate(spare):
        neighbors = [e.source for e in edges if e.target == name and e.source in positions]
        anchor = positions[neighbors[0]][1] if neighbors else 227 + i * 64
        positions[name] = (x + width * .76, anchor + i * 35)
    half = 66
    for i, edge in enumerate(edges):
        sx, sy = positions[edge.source]
        tx, ty = positions[edge.target]
        if edge.source == edge.target:
            path = f"M {sx+half} {sy-6} C {sx+half+37} {sy-30}, {sx+half+37} {sy+30}, {sx+half+2} {sy+7}"
        elif sx != tx:
            sign = 1 if tx > sx else -1
            path = f"M {sx+sign*half} {sy} L {tx-sign*(half+2)} {ty}"
        elif ty - sy == 64:
            path = f"M {sx} {sy+20} L {tx} {ty-23}"
        else:
            sign = 1 if ty > sy else -1
            if ty < sy and sy - ty == 64:
                sign = 1
            rail = sx + sign * (half + 15 + (i % 3) * 6)
            path = f"M {sx+sign*half} {sy} Q {rail} {sy}, {rail} {sy+(-10 if ty < sy else 10)} L {rail} {ty+(10 if ty<sy else -10)} Q {rail} {ty}, {tx+sign*(half+2)} {ty}"
        edge_node = element(group, "path", {"d": path, "fill": "none", "stroke": "#525e57", "stroke-width": 1.8,
                            "stroke-dasharray": "4 3" if edge.conditional else "none", "marker-end": "url(#arrow)",
                            "data-source": edge.source, "data-target": edge.target})
        element(edge_node, "title", text=f"{edge.source} → {edge.target}")
    for name, (cx, cy) in positions.items():
        node = element(group, "g", {"data-node": name})
        rect(node, cx - half, cy - 20, half * 2, 40, radius=8,
             fill="#eef1ee" if name.startswith("__") else "white", stroke="#768078")
        text(node, cx, cy - 1, LABELS.get(name, name), 13, 650, anchor="middle")
        text(node, cx, cy + 13, name, 10, color="#59655d", anchor="middle")


def export(output):
    workflow = Workflow(None, None, None)
    graphs = [compiled.get_graph() for compiled in (workflow.compiled, workflow.panel, workflow.individual)]
    outer, panel, individual = graphs
    recovery_nodes = {"__start__", "resume", "__end__"}
    primary_edges = [e for e in outer.edges if e.source not in recovery_nodes and e.target not in recovery_nodes]
    recovery_edges = [e for e in outer.edges if e not in primary_edges]
    root = ET.Element("svg", {"xmlns":"http://www.w3.org/2000/svg", "viewBox":"0 0 1100 852",
        "width":"1100", "height":"852", "role":"img", "aria-labelledby":"title description",
        "font-family":"Malgun Gothic, Apple SD Gothic Neo, Noto Sans CJK KR, sans-serif"})
    element(root, "title", {"id":"title"}, "동행 여행 조율 · LangGraph 실행 그래프")
    element(root, "desc", {"id":"description"}, "실행 중 사용하는 세 컴파일 그래프의 노드와 연결을 읽어 표시했다. 하단 표는 협상 그래프의 재진입 및 반환 경로다.")
    defs = element(root, "defs")
    marker = element(defs, "marker", {"id":"arrow","viewBox":"0 0 9 9","refX":"7","refY":"4.5","markerWidth":5,"markerHeight":5,"orient":"auto-start-reverse"})
    element(marker, "path", {"d":"M 0 0 L 8 4.5 L 0 9 z","fill":"#525e57"})
    rect(root, 0, 0, 1100, 852, fill="#f6f7f5", stroke="none", radius=0)
    text(root, 26, 39, "AI–MEDIATOR  /  LANGGRAPH", 14, 700, "#536359")
    text(root, 26, 79, "동행의 여행 조율 과정", 33, 750)
    text(root, 1080, 81, "실선 · 기본 연결   /   점선 · 조건 분기", 14, 500, "#526059", "end")
    draw_graph(root, "travel_negotiation", set(outer.nodes) - recovery_nodes, primary_edges, 22, 423, "방의 협상 단계", "합의 여부와 발언 순서에 따라 다음 단계로 이동한다.")
    draw_graph(root, "parallel_agents", panel.nodes, panel.edges, 458, 305, "참가자별 병렬 처리", "정원만큼 독립된 에이전트에 작업을 배정한다.")
    draw_graph(root, "personal_agent", individual.nodes, individual.edges, 776, 302, "개인 에이전트", "필요한 검색 근거를 개인 제안에 반영한다.")
    recovery = element(root, "g", {"data-graph": "travel_negotiation", "data-view": "resume-and-return"})
    rect(recovery, 22, 621, 1056, 204)
    text(recovery, 43, 656, "재시작과 대기 경로", 20, 700)
    text(recovery, 43, 680, "작업 임대와 저장된 단계에 따라 실행을 재개하거나 다음 실행까지 제어를 반환한다.", 13, color="#526059")
    by_source = defaultdict(list)
    for e in recovery_edges:
        by_source[e.source].append(e.target)
        title = element(recovery, "g", {"data-source":e.source, "data-target":e.target})
        element(title, "title", text=f"{e.source} → {e.target}")
    grouped = defaultdict(list)
    for source, targets in by_source.items():
        grouped[tuple(sorted(targets))].append(source)
    for i, (targets, sources) in enumerate(grouped.items()):
        text(recovery, 43, 711 + 37 * i, " · ".join(sorted(sources)) + "   →   " + " · ".join(targets), 14, 500)
    output.mkdir(parents=True, exist_ok=True)
    svg = output / "travel-graph.svg"
    ET.ElementTree(root).write(svg, encoding="utf-8", xml_declaration=True)
    return svg


def png(svg):
    inkscape = shutil.which("inkscape") or shutil.which("inkscape.com")
    if not inkscape and os.name == "nt":
        installed = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Inkscape/bin/inkscape.com"
        if installed.is_file():
            inkscape = str(installed)
    target = svg.with_suffix(".png")
    if inkscape:
        subprocess.run([inkscape, str(svg), "--export-type=png", "--export-width=1650", f"--export-filename={target}"], check=True)
    else:
        try:
            import cairosvg
        except ImportError as error:
            raise SystemExit("SVG 저장 완료. PNG 변환에는 Inkscape 또는 CairoSVG가 필요합니다.") from error
        cairosvg.svg2png(url=str(svg), write_to=str(target), output_width=1650, output_height=1278)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/langraph")
    parser.add_argument("--png", action="store_true", help="SVG와 PNG를 함께 저장")
    args = parser.parse_args()
    svg = export(args.output)
    print(svg)
    if args.png:
        print(png(svg))
