#!/usr/bin/env python3
"""Convert a DipTrace PCB XML export (.dipxml) to boardview files.

    python dip2boardview.py board.dipxml            writes board.brd and board.bvr
    python dip2boardview.py board.dipxml -f bvr     writes only one format
    python dip2boardview.py                         opens a file picker

Output formats, both readable by OpenBoardView:
    .brd  Test_Link text format. Widest viewer support; pins are numbered 1..N only.
    .bvr  BVRAW_FORMAT_3 text format. Keeps real pad numbers (A1) and pin names.

Native .dip files are binary, so export to XML from DipTrace PCB Layout first.
Only the Python standard library is needed.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

UNITS_TO_MIL = {"mm": 1 / 0.0254, "inch": 1000.0, "mil": 1.0}
SKIPPED_COMPONENT_TYPES = {"Via", "MtHole", "Fiducial"}
# The "UNCONNECTED" prefix makes OpenBoardView mark these pins as not connected.
NO_NET = "UNCONNECTED_PIN"
ARC_STEP = math.radians(5)


class ConversionError(Exception):
    """The input cannot be converted; the message is meant for the user."""


@dataclass
class Pin:
    number: str
    name: str
    x: float  # board position in mils
    y: float
    radius: float
    side: str  # T, B or O (both)
    net: str


@dataclass
class Part:
    name: str
    side: str  # T or B
    smd: bool
    x: float
    y: float
    pins: list[Pin] = field(default_factory=list)


@dataclass
class Board:
    parts: list[Part]
    outline: list[tuple[float, float]]  # contours, each ending on its first point
    warnings: list[str] = field(default_factory=list)


def real(element: ET.Element, name: str, default: float = 0.0) -> float:
    """Read a number. DipTrace omits defaults, and old exports can use decimal commas."""
    raw = element.get(name)
    if raw is None:
        return default
    return float(raw.replace(",", "."))


def clean(text: str | None) -> str:
    """Make a name safe for formats that split fields on whitespace."""
    return re.sub(r"\s+", "_", (text or "").strip())


def natural_key(text: str) -> list:
    return [(0, int(s), "") if s.isdigit() else (1, 0, s) for s in re.split(r"(\d+)", text) if s]


def child_text(element: ET.Element, tag: str) -> str:
    return clean(element.findtext(tag))


def enabled(element: ET.Element) -> bool:
    return element.get("Enabled", "Y") != "N"


def tessellate_arc(a, mid, b) -> list[tuple[float, float]]:
    """Points after `a` along the circular arc a -> mid -> b, ending on b."""
    d = 2 * (a[0] * (mid[1] - b[1]) + mid[0] * (b[1] - a[1]) + b[0] * (a[1] - mid[1]))
    if abs(d) < 1e-9:
        return [b]  # collinear, so effectively a straight edge
    a2, m2, b2 = (p[0] ** 2 + p[1] ** 2 for p in (a, mid, b))
    cx = (a2 * (mid[1] - b[1]) + m2 * (b[1] - a[1]) + b2 * (a[1] - mid[1])) / d
    cy = (a2 * (b[0] - mid[0]) + m2 * (a[0] - b[0]) + b2 * (mid[0] - a[0])) / d
    start, through, end = (math.atan2(p[1] - cy, p[0] - cx) for p in (a, mid, b))
    ccw_to_mid = (through - start) % math.tau
    ccw_to_end = (end - start) % math.tau
    # Follow the direction that passes through the middle point.
    if ccw_to_mid <= ccw_to_end:
        to_mid, sweep = ccw_to_mid, ccw_to_end
    else:
        to_mid, sweep = ccw_to_mid - math.tau, ccw_to_end - math.tau
    radius = math.hypot(a[0] - cx, a[1] - cy)

    def run(from_angle: float, span: float) -> list[tuple[float, float]]:
        steps = max(1, math.ceil(abs(span) / ARC_STEP))
        return [
            (cx + radius * math.cos(from_angle + span * i / steps), cy + radius * math.sin(from_angle + span * i / steps))
            for i in range(1, steps)
        ]

    # Two runs, so the polyline passes exactly through the stored middle point.
    return [*run(start, to_mid), mid, *run(start + to_mid, sweep - to_mid), b]


def outline_contour(points: list[ET.Element], scale: float) -> list[tuple[float, float]]:
    """Flatten outline points with Arc="Y" midpoints into a closed polyline."""
    xy = [(real(p, "X") * scale, real(p, "Y") * scale) for p in points]
    arc = [p.get("Arc", "N") == "Y" for p in points]
    n = len(xy)
    start = next((i for i in range(n) if not arc[i]), None)
    if start is None:
        raise ConversionError("The board outline has only arc midpoints, so it cannot be read.")
    contour = [xy[start]]
    consumed = 1
    i = (start + 1) % n
    while consumed < n:
        if arc[i]:
            end = (i + 1) % n
            contour.extend(tessellate_arc(contour[-1], xy[i], xy[end]))
            i = (i + 2) % n
            consumed += 2
        else:
            contour.append(xy[i])
            i = (i + 1) % n
            consumed += 1
    return close(contour)


def close(contour: list[tuple[float, float]]) -> list[tuple[float, float]]:
    # OpenBoardView finds the end of a contour by seeing its first point again.
    return contour if contour[-1] == contour[0] else contour + [contour[0]]


def cutout_contour(shape: ET.Element, scale: float, warnings: list[str]) -> list[tuple[float, float]]:
    points = shape.findall("./Points/*")
    xy = [(real(p, "X") * scale, real(p, "Y") * scale) for p in points]
    kind = shape.get("Type")
    if kind in {"Polygon", "Polyline"} and len(xy) >= 3:
        return close(xy)
    if kind in {"Rectangle", "FillRect", "Obround", "FillObround"} and len(xy) == 2:
        (x1, y1), (x2, y2) = xy
        return close([(x1, y1), (x2, y1), (x2, y2), (x1, y2)])
    warnings.append(f"Skipped a board cutout of unsupported type {kind!r}.")
    return []


def parse_board(root: ET.Element) -> Board:
    if root.tag != "Source" or root.get("Type") != "DipTrace-PCB":
        raise ConversionError(f"This is not a DipTrace PCB XML file (root Type={root.get('Type')!r}).")
    units = root.get("Units")
    if units not in UNITS_TO_MIL:
        raise ConversionError(f"Unsupported or missing Units={units!r}.")
    scale = UNITS_TO_MIL[units]
    board_node = root.find("Board")
    if board_node is None:
        raise ConversionError("The file has no <Board> section.")

    # The design cache nests the pattern library, so search at any depth.
    patterns = {p.get("PatternStyle"): p for p in root.iter("Pattern") if p.get("PatternStyle")}
    pad_styles = {s.get("Name"): s for s in root.iter("PadStyle")}
    nets = {n.get("Id"): child_text(n, "Name") for n in board_node.findall("./Nets/Net")}

    warnings: list[str] = []
    parts: list[Part] = []
    for component in board_node.findall("./Components/Component"):
        if not enabled(component) or component.get("Type") in SKIPPED_COMPONENT_TYPES:
            continue
        part = parse_component(component, patterns, pad_styles, nets, scale, warnings)
        if part:
            parts.append(part)
    if not parts:
        raise ConversionError("No components with pads were found.")

    outline: list[tuple[float, float]] = []
    outline_node = board_node.find("BoardOutline")
    points = outline_node.findall("./Points/*") if outline_node is not None and enabled(outline_node) else []
    if len(points) >= 3:
        outline.extend(outline_contour(points, scale))
    else:
        warnings.append("No board outline was found, so a rectangle around the pins is used instead.")
        outline.extend(pin_bounds_rectangle(parts))
    for shape in board_node.findall("./Shapes/Shape"):
        if shape.get("Layer") == "Board Cutout" and enabled(shape):
            outline.extend(cutout_contour(shape, scale, warnings))

    return Board(parts, outline, warnings)


def parse_component(component, patterns, pad_styles, nets, scale, warnings) -> Part | None:
    name = child_text(component, "RefDes") or f"PAD_{component.get('Id')}"
    pattern = patterns.get(component.get("PatternStyle"))
    if pattern is None:
        raise ConversionError(f"{name}: footprint {component.get('PatternStyle')!r} is not in the file.")

    footprint_pads = pattern.findall("./Pads/Pad")
    by_id = {p.get("Id"): p for p in footprint_pads}
    placed_pads = component.findall("./Pads/Pad")
    if not footprint_pads:
        return None  # mechanical part with nothing to probe

    if placed_pads and not all(p.get("Id") in by_id for p in placed_pads):
        if len(placed_pads) != len(footprint_pads):
            raise ConversionError(f"{name}: placed pads do not match the footprint pads.")
        warnings.append(f"{name}: pad Ids differ from the footprint, so pads were matched by order.")
        by_id = {placed.get("Id"): fp for placed, fp in zip(placed_pads, footprint_pads)}

    net_of = {p.get("Id"): p.get("NetId", "-1") for p in placed_pads}
    x0, y0 = real(component, "X"), real(component, "Y")
    angle = real(component, "Angle")
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    bottom = component.get("Side", "Top") == "Bottom"
    part_side = "B" if bottom else "T"

    # Keep the pads the board actually placed; older files may list none.
    pads = [(i, by_id[i]) for i in net_of] if net_of else [(p.get("Id"), p) for p in footprint_pads]
    pins = []
    any_surface = False
    for pad_id, pad in pads:
        style = pad_styles.get(pad.get("Style"))
        if style is None:
            warnings.append(f"{name}: pad style {pad.get('Style')!r} is missing; treated as a surface pad.")
        through = style is not None and style.get("Type") == "Through"
        any_surface = any_surface or not through

        # DipTrace's documented placement law. Flip flags are already baked into the footprint.
        px, py = real(pad, "X"), real(pad, "Y")
        if bottom:
            px = -px
        bx = x0 + px * cos_a - py * sin_a
        by = y0 + px * sin_a + py * cos_a

        if through:
            side = "O"
        else:
            # A footprint-local bottom pad sits on the opposite face from the part.
            local_bottom = pad.get("Side", "Top") == "Bottom"
            side = "B" if bottom != local_bottom else "T"

        number = child_text(pad, "Number") or str(pad_id)
        net = nets.get(net_of.get(pad_id, "-1"), "") or NO_NET
        pins.append(Pin(number, child_text(pad, "Note"), bx * scale, by * scale, pad_radius(style, scale), side, net))

    # Viewers number .brd pins by file order, so match the pad numbers where possible.
    pins.sort(key=lambda pin: natural_key(pin.number))
    return Part(name, part_side, any_surface, x0 * scale, y0 * scale, pins)


def pad_radius(style: ET.Element | None, scale: float) -> float:
    stack = style.find("MainStack") if style is not None else None
    if stack is None:
        return 10.0
    return max(min(real(stack, "Width"), real(stack, "Height")) * scale / 2, 1.0)


def pin_bounds_rectangle(parts: list[Part]) -> list[tuple[float, float]]:
    xs = [pin.x for part in parts for pin in part.pins]
    ys = [pin.y for part in parts for pin in part.pins]
    margin = 100.0
    x1, y1, x2, y2 = min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin
    return close([(x1, y1), (x2, y1), (x2, y2), (x1, y2)])


class Grid:
    """Rounds to whole viewer units (1 unit = 1 mil), with the board origin moved to 0,0."""

    def __init__(self, board: Board):
        xs = [p[0] for p in board.outline] + [pin.x for part in board.parts for pin in part.pins]
        ys = [p[1] for p in board.outline] + [pin.y for part in board.parts for pin in part.pins]
        self.x0, self.y0 = min(xs), min(ys)

    def __call__(self, x: float, y: float) -> tuple[int, int]:
        return round(x - self.x0), round(y - self.y0)


def to_brd(board: Board) -> str:
    grid = Grid(board)
    outline = dedupe([grid(*p) for p in board.outline])
    pin_count = sum(len(part.pins) for part in board.parts)
    pin_nets = [pin.net for part in board.parts for pin in part.pins]
    lines = [
        "str_length:",
        f"{sum(len(part.name) + 1 for part in board.parts)} {sum(len(net) + 1 for net in pin_nets)}",
        "var_data:",
        f"{len(outline)} {len(board.parts)} {pin_count} 0 0 0",
        "Format:",
    ]
    lines += [f"{x} {y}" for x, y in outline]
    lines.append("Parts:")
    end_of_pins = 0
    for part in board.parts:
        end_of_pins += len(part.pins)
        kind = {("T", True): 5, ("B", True): 10, ("T", False): 1, ("B", False): 2}[part.side, part.smd]
        lines.append(f"{part.name} {kind} {end_of_pins}")
    lines.append("Pins:")
    for index, part in enumerate(board.parts, start=1):
        for pin in part.pins:
            x, y = grid(pin.x, pin.y)
            lines.append(f"{x} {y} -99 {index} {pin.net}")  # -99 means no test probe
    lines.append("Nails:")
    return "\n".join(lines) + "\n"


def to_bvr(board: Board) -> str:
    grid = Grid(board)
    lines = ["BVRAW_FORMAT_3"]
    for part in board.parts:
        ox, oy = grid(part.x, part.y)
        lines += [
            f"PART_NAME {part.name}",
            f"   PART_SIDE {part.side}",
            f"   PART_ORIGIN {ox} {oy}",
            f"   PART_MOUNT {'SMD' if part.smd else 'THROUGH'}",
        ]
        for index, pin in enumerate(part.pins, start=1):
            x, y = grid(pin.x, pin.y)
            lines += [f"   PIN_ID {index}", f"      PIN_NUMBER {pin.number}"]
            if pin.name:
                lines.append(f"      PIN_NAME {pin.name}")
            lines += [
                f"      PIN_SIDE {pin.side}",
                f"      PIN_ORIGIN {x - ox} {y - oy}",  # relative to PART_ORIGIN
                f"      PIN_RADIUS {pin.radius:.1f}",
                f"      PIN_NET {pin.net}",
                "   PIN_END",
            ]
        lines.append("PART_END")
    outline = dedupe([grid(*p) for p in board.outline])
    lines.append("OUTLINE_POINTS " + " ".join(f"{x} {y}" for x, y in outline))
    return "\n".join(lines) + "\n"


def dedupe(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Drop repeats caused by rounding, which would hide a contour's end from the viewer."""
    return [p for i, p in enumerate(points) if i == 0 or p != points[i - 1]]


WRITERS = {"brd": to_brd, "bvr": to_bvr}


def load(path: Path) -> ET.Element:
    with path.open("rb") as handle:
        magic = handle.read(16)
    if magic[1:8] == b"DTBOARD":
        raise ConversionError(
            f"{path.name} is a binary DipTrace board. In DipTrace PCB Layout, export it "
            "to DipTrace XML from the File menu, then convert the .dipxml file."
        )
    try:
        return ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ConversionError(f"{path.name} is not valid XML: {exc}") from exc


def convert(path: Path, formats: list[str], out_dir: Path | None = None) -> tuple[list[Path], Board]:
    board = parse_board(load(path))
    written = []
    for fmt in formats:
        target = (out_dir or path.parent) / f"{path.stem}.{fmt}"
        target.write_text(WRITERS[fmt](board), encoding="utf-8", newline="\n")
        written.append(target)
    return written, board


def summary(written: list[Path], board: Board) -> str:
    pins = sum(len(part.pins) for part in board.parts)
    connected = sum(pin.net != NO_NET for part in board.parts for pin in part.pins)
    lines = [f"{len(board.parts)} parts, {pins} pins, {connected} connected to a net"]
    lines += [f"Wrote {path}" for path in written]
    lines += [f"Warning: {warning}" for warning in board.warnings]
    return "\n".join(lines)


def run_gui(formats: list[str]) -> int:
    import tkinter
    from tkinter import filedialog, messagebox

    window = tkinter.Tk()
    window.withdraw()
    chosen = filedialog.askopenfilename(
        title="Choose a DipTrace XML export",
        filetypes=[("DipTrace PCB XML", "*.dipxml *.xml"), ("All files", "*.*")],
    )
    if not chosen:
        return 0
    try:
        messagebox.showinfo("DipTrace to boardview", summary(*convert(Path(chosen), formats)))
        return 0
    except (ConversionError, OSError, ValueError) as exc:
        messagebox.showerror("DipTrace to boardview", str(exc))
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert a DipTrace .dipxml export to boardview files.")
    parser.add_argument("input", nargs="*", type=Path, help=".dipxml file(s); omit to open a file picker")
    parser.add_argument("-f", "--format", choices=["brd", "bvr", "both"], default="both")
    parser.add_argument("-o", "--out-dir", type=Path, help="output folder (default: next to the input)")
    args = parser.parse_args(argv)
    formats = list(WRITERS) if args.format == "both" else [args.format]

    if not args.input:
        return run_gui(formats)
    status = 0
    for path in args.input:
        try:
            print(summary(*convert(path, formats, args.out_dir)))
        except (ConversionError, OSError, ValueError) as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
