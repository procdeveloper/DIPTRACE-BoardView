"""Tests against a board written from DipTrace's XML spec, with hand-calculated positions.

Run with: python -m unittest -v test_dip2boardview
"""

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import dip2boardview as d

BOARD = """<?xml version="1.0" encoding="UTF-8"?>
<Source Type="DipTrace-PCB" Version="5.3.5.1" Units="mm">
  <Library Type="DipTrace-ComponentLibrary">
    <Library Type="DipTrace-PatternLibrary">
      <PadStyles>
        <PadStyle Name="SMT" Type="Surface"><MainStack Shape="Rectangle" Width="1" Height="0.5"/></PadStyle>
        <PadStyle Name="THT" Type="Through" Hole="0.9"><MainStack Shape="Ellipse" Width="1.6" Height="1.6"/></PadStyle>
      </PadStyles>
      <Patterns>
        <Pattern Id="0" PatternStyle="R0805">
          <Pads>
            <Pad Id="1" Style="SMT" X="-1" Y="0"><Number>1</Number><Note/></Pad>
            <Pad Id="2" Style="SMT" X="1" Y="0"><Number>2</Number><Note/></Pad>
          </Pads>
        </Pattern>
        <Pattern Id="1" PatternStyle="HDR">
          <Pads>
            <Pad Id="1" Style="THT" X="0" Y="0"><Number>10</Number></Pad>
            <Pad Id="2" Style="THT" X="2.54" Y="0"><Number>2</Number></Pad>
          </Pads>
        </Pattern>
        <Pattern Id="2" PatternStyle="BGA">
          <Pads>
            <Pad Id="1" Style="SMT" X="-1" Y="1"><Number>A1</Number><Note>VDD IO</Note></Pad>
            <Pad Id="2" Style="SMT" X="1" Y="1"><Number>A2</Number><Note>RST</Note></Pad>
          </Pads>
        </Pattern>
        <Pattern Id="3" PatternStyle="HOLE"><Holes><Hole X="0" Y="0" Diam="3" HoleDiam="3"/></Holes></Pattern>
      </Patterns>
    </Library>
  </Library>
  <Board>
    <BoardOutline>
      <Points>
        <Point X="0" Y="0"/><Point X="50" Y="0"/><Point X="50" Y="40"/><Point X="0" Y="40"/>
      </Points>
    </BoardOutline>
    <Components>
      <Component Id="0" PatternStyle="R0805" X="10" Y="10" Side="Top">
        <RefDes>R1</RefDes>
        <Pads><Pad Id="1" NetId="0"/><Pad Id="2" NetId="1"/></Pads>
      </Component>
      <Component Id="1" PatternStyle="R0805" X="20" Y="10" Angle="1.5707963268" Side="Bottom">
        <RefDes>R2</RefDes>
        <Pads><Pad Id="1" NetId="0"/><Pad Id="2"/></Pads>
      </Component>
      <Component Id="2" PatternStyle="HDR" X="30" Y="20" Side="Top">
        <RefDes>J 1</RefDes>
        <Pads><Pad Id="1" NetId="1"/><Pad Id="2" NetId="1"/></Pads>
      </Component>
      <Component Id="3" PatternStyle="BGA" X="30,5" Y="30" Side="Top">
        <RefDes>U1</RefDes>
        <Pads><Pad Id="1" NetId="1"/><Pad Id="2" NetId="0"/></Pads>
      </Component>
      <Component Id="4" PatternStyle="HOLE" X="5" Y="5"><RefDes>MH1</RefDes></Component>
      <Component Id="5" Type="Via" ViaStyle="0" X="6" Y="6"><Pads><Pad Id="1" NetId="0"/></Pads></Component>
      <Component Id="6" PatternStyle="R0805" X="1" Y="1" Enabled="N">
        <RefDes>DEAD</RefDes><Pads><Pad Id="1"/><Pad Id="2"/></Pads>
      </Component>
    </Components>
    <Nets>
      <Net Id="0"><Name>GND</Name></Net>
      <Net Id="1"><Name>V 3V3</Name></Net>
    </Nets>
    <Shapes>
      <Shape Id="0" Type="Rectangle" Layer="Board Cutout">
        <Points><Point X="40" Y="30"/><Point X="45" Y="35"/></Points>
      </Shape>
    </Shapes>
  </Board>
</Source>
"""

MIL = 1 / 0.0254


def board(xml=BOARD):
    return d.parse_board(ET.fromstring(xml))


def read_brd(text):
    """Parse the way OpenBoardView's BRDFile does, including its bounds checks."""
    assert "str_length:" in text and "var_data:" in text
    blocks = {"str_length:": 1, "var_data:": 2, "Format:": 3, "Parts:": 4, "Pins:": 5, "Nails:": 6}
    block, seen = 0, []
    counts, fmt, parts, pins = None, [], [], []
    for line in text.splitlines():
        if line in blocks:
            block = blocks[line]
            seen.append(block)
        elif block == 2:
            counts = [int(v) for v in line.split()][:4]
        elif block == 3:
            assert len(fmt) < counts[0]
            fmt.append(tuple(int(v) for v in line.split()))
        elif block == 4:
            assert len(parts) < counts[1]
            name, kind, end = line.split()
            assert int(end) <= counts[2]
            parts.append((name, int(kind), int(end)))
        elif block == 5:
            assert len(pins) < counts[2]
            x, y, probe, part, net = line.split()
            assert 1 <= int(part) <= counts[1]
            pins.append((int(x), int(y), int(probe), int(part), net))
    assert seen == [1, 2, 3, 4, 5, 6], "blocks must appear in the documented order"
    assert (len(fmt), len(parts), len(pins)) == tuple(counts[:3]), "declared counts must be exact"
    return fmt, parts, pins


class Geometry(unittest.TestCase):
    def setUp(self):
        self.parts = {p.name: p for p in board().parts}

    def test_skips_vias_mechanical_and_disabled(self):
        self.assertEqual(list(self.parts), ["R1", "R2", "J_1", "U1"])

    def test_top_placement(self):
        pin = self.parts["R1"].pins[0]
        self.assertAlmostEqual(pin.x, 9 * MIL, places=3)
        self.assertAlmostEqual(pin.y, 10 * MIL, places=3)

    def test_bottom_placement_mirrors_then_rotates(self):
        # Pad 1 at (-1, 0) mirrors to (1, 0), then 90 degrees CCW gives (0, 1).
        pin = self.parts["R2"].pins[0]
        self.assertAlmostEqual(pin.x, 20 * MIL, places=3)
        self.assertAlmostEqual(pin.y, 11 * MIL, places=3)

    def test_sides_and_mounting(self):
        self.assertEqual((self.parts["R1"].side, self.parts["R1"].smd, self.parts["R1"].pins[0].side), ("T", True, "T"))
        self.assertEqual((self.parts["R2"].side, self.parts["R2"].pins[0].side), ("B", "B"))
        self.assertEqual((self.parts["J_1"].smd, self.parts["J_1"].pins[0].side), (False, "O"))

    def test_nets(self):
        self.assertEqual(self.parts["R1"].pins[0].net, "GND")
        self.assertEqual(self.parts["R1"].pins[1].net, "V_3V3")
        self.assertEqual(self.parts["R2"].pins[1].net, d.NO_NET)

    def test_pins_in_natural_number_order(self):
        self.assertEqual([p.number for p in self.parts["J_1"].pins], ["2", "10"])

    def test_decimal_comma(self):
        self.assertAlmostEqual(self.parts["U1"].x, 30.5 * MIL, places=3)

    def test_inch_units(self):
        xml = BOARD.replace('Units="mm"', 'Units="inch"')
        self.assertAlmostEqual(board(xml).parts[0].pins[0].x, 9000, places=3)


class Outline(unittest.TestCase):
    def contours(self, points):
        contours, current = [], []
        for point in points:
            current.append(point)
            if len(current) > 1 and point == current[0]:
                contours.append(current)
                current = []
        self.assertEqual(current, [], "every contour must end on its first point")
        return contours

    def test_outline_and_cutout_are_separate_closed_contours(self):
        contours = self.contours(board().outline)
        self.assertEqual([len(c) for c in contours], [5, 5])

    def test_arc_passes_through_midpoint(self):
        xml = BOARD.replace(
            '<Point X="50" Y="40"/>', '<Point X="60" Y="20" Arc="Y"/><Point X="50" Y="40"/>'
        )
        outline = self.contours(board(xml).outline)[0]
        self.assertGreater(len(outline), 10)
        self.assertAlmostEqual(max(p[0] for p in outline), 60 * MIL, delta=1)
        self.assertEqual(outline[0], outline[-1])

    def test_arc_marker_on_first_point_wraps(self):
        xml = BOARD.replace(
            '<Point X="0" Y="0"/><Point X="50" Y="0"/><Point X="50" Y="40"/><Point X="0" Y="40"/>',
            '<Point X="-10" Y="20" Arc="Y"/><Point X="0" Y="0"/><Point X="50" Y="0"/>'
            '<Point X="50" Y="40"/><Point X="0" Y="40"/>',
        )
        outline = self.contours(board(xml).outline)[0]
        self.assertAlmostEqual(min(p[0] for p in outline), -10 * MIL, delta=1)
        self.assertAlmostEqual(max(p[0] for p in outline), 50 * MIL, delta=1)

    def test_missing_outline_uses_pin_bounds_and_warns(self):
        start, end = BOARD.index("<BoardOutline>"), BOARD.index("</BoardOutline>")
        result = board(BOARD[:start] + BOARD[end + len("</BoardOutline>"):])
        self.assertTrue(any("outline" in w for w in result.warnings))
        self.contours(result.outline)


class Writers(unittest.TestCase):
    def test_brd_passes_the_parser_checks(self):
        fmt, parts, pins = read_brd(d.to_brd(board()))
        self.assertEqual(parts, [("R1", 5, 2), ("R2", 10, 4), ("J_1", 1, 6), ("U1", 5, 8)])
        self.assertEqual(len(pins), 8)
        self.assertEqual(pins[0][2:], (-99, 1, "GND"))
        self.assertEqual(pins[3][4], d.NO_NET)
        self.assertEqual(fmt[0], fmt[4], "outline must be closed")
        self.assertEqual(min(x for x, _ in fmt), 0)

    def test_brd_position_in_mils(self):
        _, _, pins = read_brd(d.to_brd(board()))
        self.assertEqual(pins[0][:2], (354, 394))  # 9 mm, 10 mm

    def test_bvr_keeps_pad_numbers_and_names(self):
        text = d.to_bvr(board())
        self.assertEqual(text.splitlines()[0], "BVRAW_FORMAT_3")
        self.assertIn("PIN_NUMBER A1", text)
        self.assertIn("PIN_NAME VDD_IO", text)
        self.assertEqual(text.count("PIN_END"), 8)
        self.assertEqual(text.count("PART_END"), 4)

    def test_bvr_pin_origin_resolves_to_same_position_as_brd(self):
        _, _, brd_pins = read_brd(d.to_brd(board()))
        positions, ox, oy = [], 0, 0
        for line in d.to_bvr(board()).splitlines():
            fields = line.split()
            if fields[0] == "PART_ORIGIN":
                ox, oy = int(fields[1]), int(fields[2])
            elif fields[0] == "PIN_ORIGIN":
                positions.append((int(fields[1]) + ox, int(fields[2]) + oy))
        self.assertEqual(positions, [p[:2] for p in brd_pins])


class Errors(unittest.TestCase):
    def test_binary_dip_gets_export_instructions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "board.dip"
            path.write_bytes(b"\x07DTBOARD\x0fBv;" + b"\0" * 32)
            with self.assertRaisesRegex(d.ConversionError, "export"):
                d.load(path)

    def test_wrong_root_rejected(self):
        with self.assertRaisesRegex(d.ConversionError, "not a DipTrace PCB"):
            board('<Source Type="DipTrace-Schematic" Units="mm"/>')

    def test_missing_footprint_rejected(self):
        with self.assertRaisesRegex(d.ConversionError, "R1"):
            board(BOARD.replace('PatternStyle="R0805" X="10"', 'PatternStyle="NOPE" X="10"'))

    def test_convert_writes_both_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "board.dipxml"
            path.write_text(BOARD, encoding="utf-8")
            written, _ = d.convert(path, ["brd", "bvr"])
            self.assertEqual([p.name for p in written], ["board.brd", "board.bvr"])
            read_brd(written[0].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
