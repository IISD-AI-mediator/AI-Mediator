"""Draw the roles and handoffs of the live, compiled travel graphs without model calls."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from travel_app.graph import Workflow


WIDTH, HEIGHT = 1600, 1100
START, END = "__start__", "__end__"
INK, MUTED, RULE = "#182d32", "#485f64", "#aabbb9"
TEAL, BLUE, OCHRE, PURPLE = "#116657", "#245499", "#895023", "#64458d"
PAPER = "#f8f8f3"


def element(parent, tag, attrs=None, content=None):
    child = ET.SubElement(parent, tag, {key: str(value) for key, value in (attrs or {}).items()})
    child.text = content
    return child


def text(parent, x, y, value, size=16, weight=400, color=INK, anchor="start"):
    return element(parent, "text", {"x": x, "y": y, "font-size": size, "font-weight": weight,
                                    "fill": color, "text-anchor": anchor}, value)


def box(parent, x, y, width, height, fill, stroke="none", radius=10):
    return element(parent, "rect", {"x": x, "y": y, "width": width, "height": height, "rx": radius,
                                    "fill": fill, "stroke": stroke, "stroke-width": 1.5})


def path(parent, route, color, *, dash=None, arrow=False):
    attrs = {"d": route, "fill": "none", "stroke": color, "stroke-width": 2.2,
             "stroke-linejoin": "round", "stroke-linecap": "round"}
    if dash:
        attrs["stroke-dasharray"] = dash
    if arrow:
        attrs["marker-end"] = "url(#return-arrow)" if color == OCHRE else "url(#arrow)"
    return element(parent, "path", attrs)


class GraphView:
    """Bind annotations to compiled nodes and edges, and reject unrepresented topology."""

    def __init__(self, root, compiled):
        self.name = compiled.name
        self.group = element(root, "g", {"data-graph": self.name})
        graph = compiled.get_graph()
        self.nodes = set(graph.nodes)
        self.edges = {(e.source, e.target): e.conditional for e in graph.edges}
        if len(self.edges) != len(graph.edges):
            raise ValueError(f"{self.name}: parallel edges between the same nodes need distinct annotations")

    def node(self, name, parent=None):
        if name not in self.nodes:
            raise ValueError(f"{self.name}: missing or repeated diagram node {name}")
        self.nodes.remove(name)
        return element(self.group if parent is None else parent, "g", {"data-node": name})

    def edge(self, source, target, conditional, route=None, parent=None, *, returning=False):
        if self.edges.pop((source, target), None) != conditional:
            raise ValueError(f"{self.name}: route {source} → {target} is missing or its type changed")
        parent = self.group if parent is None else parent
        group = element(parent, "g", {"data-source": source, "data-target": target,
                                      "data-conditional": str(conditional).lower()})
        element(group, "title", content=f"{source} → {target}")
        if route:
            path(group, route, OCHRE if returning else MUTED, dash="6 5" if conditional else None, arrow=True)

    def check_complete(self):
        if self.nodes or self.edges:
            raise ValueError(f"Update the {self.name} diagram for nodes {self.nodes} and edges {self.edges}")


def card(view, name, x, y, width, height, owner, action, detail, color, fill="white"):
    g = view.node(name)
    box(g, x, y, width, height, fill, color)
    text(g, x + 14, y + 24, owner, 15, 700, color)
    text(g, x + width - 13, y + 24, name, 14, 500, color, "end")
    text(g, x + 14, y + 59, action, 21, 700)
    text(g, x + 14, y + 85, detail, 14, 400, MUTED)


def endpoint(view, name, x, y, label):
    g = view.node(name)
    element(g, "circle", {"cx": x, "cy": y, "r": 5, "fill": INK})
    text(g, x, y + 26, label, 14, 600, MUTED, "middle")


def header(root):
    defs = element(root, "defs")
    for name, color in [("arrow", MUTED), ("return-arrow", OCHRE)]:
        marker = element(defs, "marker", {"id": name, "viewBox": "0 0 8 8", "refX": 7, "refY": 4,
                                         "markerWidth": 5, "markerHeight": 5, "orient": "auto"})
        element(marker, "path", {"d": "M0 0L8 4L0 8Z", "fill": color})
    box(root, 0, 0, WIDTH, HEIGHT, PAPER, radius=0)
    text(root, 40, 36, "AI–MEDIATOR   /   LANGGRAPH", 15, 700, TEAL)
    text(root, 40, 82, "여행 협상의 역할과 책임", 40, 700)
    text(root, 42, 115, "생성자가 역할을 나누고, 개인 에이전트가 제안하며, 판사가 토론과 확정을 결정한다.", 19, 400, MUTED)
    for x, label, color, dash in [(955, "기본 전이", MUTED, None), (1100, "조건 전이", MUTED, "6 5"),
                                  (1245, "반복 전이", OCHRE, "6 5"), (1390, "호출 상세", BLUE, "2 5")]:
        path(root, f"M{x} 82 h34", color, dash=dash, arrow=color != BLUE)
        text(root, x + 44, 88, label, 15, 600, color)
    path(root, "M40 140 H1560", RULE)


def negotiation(view):
    g = view.group
    text(g, 42, 176, "방 단위 협상", 24, 700)
    text(g, 213, 175, "travel_negotiation", 16, 500, MUTED)
    box(g, 856, 303, 721, 195, "#faf4ea", "#d8c6ad", 13)
    text(g, 872, 338, "쟁점 토론", 19, 700, OCHRE)
    for source, target, route in [
        ("team", "propose", "M254 242 H296"),
        ("propose", "judge", "M545 242 H597"),
        ("judge", "final", "M839 242 H1330"),
        ("judge", "open", "M781 297 V402 H869"),
        ("open", "floor", "M1050 402 H1086"),
        ("floor", "speak", "M1284 402 H1382"),
    ]:
        view.edge(source, target, True, route)
    for source, target, route in [
        ("floor", "floor", "M1161 351 V331 H1219 V349"),
        ("speak", "floor", "M1474 455 V477 H1243 V457"),
        ("floor", "judge", "M1112 455 V533 H722 V299"),
    ]:
        view.edge(source, target, True, route, returning=True)
    text(g, 1085, 229, "충돌 없음 또는 토론 회차 소진", 17, 700, MUTED, "middle")
    text(g, 787, 365, "충돌 있고", 14, 600, MUTED)
    text(g, 787, 388, "회차 남음", 14, 600, MUTED)
    text(g, 1334, 391, "차례·지시 있음", 14, 600, MUTED, "middle")
    text(g, 1190, 323, "순서 재확인", 14, 600, OCHRE, "middle")
    text(g, 1358, 496, "발언 후", 14, 600, OCHRE, "middle")
    text(g, 906, 524, "마감 후 대기 발언·지시 처리 완료", 15, 600, OCHRE, "middle")
    card(view, "team", 40, 193, 214, 103, "생성자", "역할 배정", "참가자별 임무와 조건 배정", TEAL, "#e7f2ed")
    card(view, "propose", 299, 193, 246, 103, "협상 실행기", "개인 제안 수집", "참가자 전원의 제안 확인", BLUE, "#eaf0f9")
    card(view, "judge", 599, 193, 240, 103, "판사 에이전트", "여행 조건 판정", "제안·근거·이전 판단을 함께 검토", OCHRE, "#f7ead7")
    card(view, "final", 1333, 193, 227, 103, "협상 실행기", "최종 여행안 게시", "확정 조건과 미해결 항목 기록", BLUE, "#eaf0f9")
    card(view, "open", 872, 352, 178, 103, "판사 에이전트", "토론 열기", "쟁점 공지와 대기열 생성", OCHRE)
    card(view, "floor", 1089, 352, 195, 103, "발언 진행 시스템", "발언자 지정", "대기열·미처리 지시 확인", BLUE)
    card(view, "speak", 1385, 352, 175, 103, "개인 에이전트", "입장 발언", "지시·희망 조건 반영", PURPLE)


def parallel(panel, personal):
    g = panel.group
    # This detail link expands the outer propose invocation without adding a graph edge.
    path(g, "M422 298 V551", BLUE, dash="2 5")
    text(g, 443, 414, "하위 그래프 호출", 17, 700, BLUE)
    text(g, 443, 440, "참가자별 제안 수집", 16, 400, MUTED)
    box(g, 40, 552, 1520, 328, "#eff4fa", "#bbcbdc", 15)
    text(g, 63, 592, "참가자별 병렬 제안", 25, 700)
    text(g, 306, 592, "parallel_agents", 16, 500, BLUE)
    endpoint(panel, START, 78, 742, "시작")
    panel.edge(START, "personal_agent", True, "M85 742 H344")
    text(g, 213, 726, "Send × 참가자 수", 20, 700, BLUE, "middle")
    text(g, 213, 770, "개인 조건·역할을 1건씩 전달", 15, 400, MUTED, "middle")

    worker = panel.node("personal_agent")
    box(worker, 356, 617, 746, 226, "#dde4f1", "#adbbce")
    box(worker, 351, 622, 746, 226, "#e7eaf4", "#adbbce")
    box(worker, 346, 627, 746, 226, "white", "#9184aa")
    text(worker, 368, 665, "개인 에이전트", 23, 700, PURPLE)
    text(worker, 1070, 665, "personal_agent × N", 16, 600, PURPLE, "end")
    panel.edge("personal_agent", END, False, "M1103 742 H1510")
    endpoint(panel, END, 1518, 742, "반환")
    text(g, 1138, 693, "결과 병합", 18, 700, BLUE)
    text(g, 1138, 722, "answers 리듀서가 제안 목록을 병합 (operator.add)", 16)
    text(g, 1138, 785, "상위 propose", 17, 700, BLUE)
    text(g, 1138, 815, "모든 제안을 확인해 판사에게 전달한다.", 16)

    p = personal.group
    personal.edge(START, "interpret", False, "M385 742 H416")
    personal.edge("interpret", "search", True, "M571 742 H650")
    personal.edge("interpret", "propose", True, "M495 778 V820 H861 V762 H884")
    personal.edge("search", "propose", False, "M819 742 H884")
    personal.edge("propose", END, False, "M1033 742 H1063")
    text(p, 610, 731, "항목 있음", 14, 600, MUTED, "middle")
    text(p, 674, 812, "검색 항목 없음", 15, 600, MUTED, "middle")
    endpoint(personal, START, 379, 742, "시작")
    endpoint(personal, END, 1070, 742, "반환")
    for name, x, width, label, detail in [
        ("interpret", 418, 153, "개인 조건 해석", "검색 항목 · searches"),
        ("search", 652, 167, "Google 근거 검색", "검색 근거 · evidence"),
        ("propose", 886, 147, "개인 제안 작성", "조건·근거 반영"),
    ]:
        node = personal.node(name)
        box(node, x, 710, width, 68, "#f4f1f8", "#b7a8c8", 7)
        text(node, x + width / 2, 739, label, 18, 700, INK, "middle")
        text(node, x + width / 2, 764, detail, 14, 400, MUTED, "middle")


def recovery(view):
    g = element(view.group, "g", {"data-view": "resume-and-return"})
    path(g, "M40 911 H1560", RULE)
    text(g, 41, 948, "실행기의 재진입과 반환", 23, 700)
    text(g, 41, 979, "방 DB에 저장된 단계와 실행 시각을 확인한다.", 16, 400, MUTED)
    text(g, 41, 1006, "대기 중인 방은 마감이나 새 지시에 다시 실행한다.", 16, 400, MUTED)
    columns = [(530, START, "시작", "방 실행 요청"), (815, "resume", "저장 단계 확인", "실행 시각이 되면 해당 단계로 재개"),
               (1241, END, "호출 반환", "대기·오류·완료 시 이번 호출 종료")]
    for x, key, title, detail in columns:
        node = view.node(key, g)
        text(node, x, 947, title, 19, 700)
        text(node, x, 973, key, 15, 500, MUTED)
        text(node, x, 1000, detail, 15)
    view.edge(START, "resume", False, "M604 940 H800", g)
    view.edge("resume", END, True, "M986 940 H1224", g)
    steps = ["team", "propose", "judge", "open", "floor", "speak", "final"]
    for step in steps:
        view.edge("resume", step, True, parent=g)
        view.edge(step, END, True, parent=g)
    text(g, 530, 1031, "resume → 저장된 협상 단계     /     모든 협상 단계 → 호출 반환 가능", 15, 600, MUTED)


def references(root):
    path(root, "M40 1050 H1560", RULE)
    text(root, 41, 1082, "강의 개념", 16, 700)
    for x, label in [(147, "7주차 61·105쪽  상태와 리듀서"), (472, "8주차 4–6쪽  조건 전이"),
                     (775, "9주차 70·73쪽  Send 병렬 실행"), (1137, "11주차 59·62쪽  역할과 서브그래프")]:
        text(root, x, 1082, label, 15, 500, MUTED)



def export(output):
    workflow = Workflow(None, None, None)
    root = ET.Element("svg", {"xmlns": "http://www.w3.org/2000/svg", "viewBox": f"0 0 {WIDTH} {HEIGHT}",
                              "width": str(WIDTH), "height": str(HEIGHT), "role": "img",
                              "aria-labelledby": "title description",
                              "font-family": "Malgun Gothic, Apple SD Gothic Neo, Noto Sans CJK KR, sans-serif"})
    element(root, "title", {"id": "title"}, "여행 협상의 역할과 책임")
    element(root, "desc", {"id": "description"},
            "생성자가 역할을 배정한다. 협상 실행기는 Send로 개인 에이전트를 병렬 호출한다. 개인 에이전트는 "
            "각자의 조건을 해석하고 필요할 때 검색해 제안을 낸다. 리듀서가 결과를 모으면 실행기가 전원을 확인한다. "
            "판사는 충돌과 남은 회차에 따라 토론을 열거나 최종안을 게시하도록 한다. 토론 중에는 발언 순서를 "
            "관리하고 마감 후 대기 발언과 지시를 모두 처리해 다시 판단한다. 실행기는 방 DB의 단계에서 재개한다.")
    header(root)
    outer = GraphView(root, workflow.compiled)
    panel = GraphView(root, workflow.panel)
    personal = GraphView(root, workflow.individual)
    negotiation(outer)
    parallel(panel, personal)
    recovery(outer)
    references(root)
    for view in (outer, panel, personal):
        view.check_complete()
    output.mkdir(parents=True, exist_ok=True)
    svg = output / "travel-graph.svg"
    ET.indent(root)
    ET.ElementTree(root).write(svg, encoding="utf-8", xml_declaration=True)
    return svg


def png(svg):
    target = svg.with_suffix(".png")
    inkscape = shutil.which("inkscape") or shutil.which("inkscape.com")
    if not inkscape and os.name == "nt":
        installed = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Inkscape/bin/inkscape.com"
        if installed.is_file():
            inkscape = str(installed)
    if inkscape:
        subprocess.run([inkscape, str(svg), "--export-type=png", f"--export-width={WIDTH * 2}",
                        f"--export-filename={target}"], check=True)
    else:
        try:
            import cairosvg
        except ImportError:
            # Optional alternative where the host provides Node.js and sharp.
            node = shutil.which("node")
            if not node or subprocess.run([node, "-e", "require.resolve('sharp')"],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
                raise SystemExit("SVG 저장 완료. PNG 변환에는 Inkscape, CairoSVG 또는 Node.js의 sharp가 필요합니다.")
            render = ("require('sharp')(process.argv[1], {density:144})"
                      ".png().toFile(process.argv[2]).catch(e => {console.error(e); process.exitCode=1})")
            subprocess.run([node, "-e", render, str(svg), str(target)], check=True)
        else:
            cairosvg.svg2png(url=str(svg), write_to=str(target), output_width=WIDTH * 2)
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
