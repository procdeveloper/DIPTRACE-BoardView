import sys, math, collections, re
import xml.etree.ElementTree as ET
sys.path.insert(0, sys.argv[2])
import dip2boardview as d
import test_dip2boardview as t

xml = sys.argv[1]
root = ET.parse(xml).getroot()
b = root.find("Board")
board = d.parse_board(root)
print("warnings:", board.warnings)

# Rebuild pin lookup independently keyed by (component Id, pad Id).
comps = {c.get("Id"): c for c in b.findall("./Components/Component")}
pats = {p.get("PatternStyle"): p for p in root.iter("Pattern")}
parts = {p.name: p for p in board.parts}
scale = d.UNITS_TO_MIL["mm"]
layers = [l.get("Id") for l in b.findall("./CopperLayers/Lay")]
print("copper layers", layers, [l.findtext("Name") for l in b.findall("./CopperLayers/Lay")])
top, bot = layers[0], layers[-1]

def pin_for(comp_id, pad_id):
    c = comps.get(comp_id)
    if c is None or c.get("Type") in d.SKIPPED_COMPONENT_TYPES: return None
    part = parts.get(d.clean(c.findtext("RefDes")))
    if part is None: return None
    fp = {x.get("Id"): x for x in pats[c.get("PatternStyle")].findall("./Pads/Pad")}
    number = d.clean(fp[pad_id].findtext("Number")) or pad_id
    return next((p for p in part.pins if p.number == number), None)

dists, side_bad, net_bad, checked, side_checked = [], [], [], 0, 0
by_side = collections.Counter()
for net in b.findall("./Nets/Net"):
    name = d.clean(net.findtext("Name"))
    for tr in net.findall("./Traces/Trace"):
        pts = tr.findall("./Points/*")
        if len(pts) < 2: continue
        for n, pt, seg in ((1, pts[0], pts[1]), (2, pts[-1], pts[-1])):
            if tr.get(f"Connected{n}") != "Pad": continue
            pin = pin_for(tr.get(f"Object{n}"), tr.get(f"SubObject{n}"))
            if pin is None: continue
            checked += 1
            dist = math.hypot(pin.x/scale - d.real(pt,"X"), pin.y/scale - d.real(pt,"Y"))
            ref = comps[tr.get(f"Object{n}")]
            dists.append((dist, ref.findtext("RefDes"), pin.number, ref.get("Side"), ref.get("Angle")))
            by_side[ref.get("Side")] += 1
            if pin.net != name: net_bad.append((ref.findtext("RefDes"), pin.number, pin.net, name))
            if pin.side in "TB":
                side_checked += 1
                lay = seg.get("Lay")
                want = top if pin.side == "T" else bot
                if lay != want: side_bad.append((ref.findtext("RefDes"), pin.number, pin.side, lay))
dists.sort(reverse=True)
print(f"trace endpoints on pads checked: {checked}  by part side: {dict(by_side)}")
print("worst pad-to-trace distance (mm):", [(round(x[0],4),)+x[1:] for x in dists[:6]])
print("over 0.05mm:", sum(x[0] > 0.05 for x in dists), " over 0.5mm:", sum(x[0] > 0.5 for x in dists))
print(f"SMD side checks: {side_checked}, mismatches: {side_bad[:10]} ({len(side_bad)})")
print("net mismatches:", net_bad[:10], len(net_bad))

# Net pad lists are DipTrace's own mirror of membership.
mirror_bad = 0; mirror_n = 0
for net in b.findall("./Nets/Net"):
    name = d.clean(net.findtext("Name"))
    for it in net.findall("./Pads/Item"):
        pin = pin_for(it.get("Comp"), it.get("Pad"))
        if pin is None: continue
        mirror_n += 1
        mirror_bad += pin.net != name
print(f"net <Pads> list entries checked: {mirror_n}, mismatches: {mirror_bad}")

# Anything skipped, and does outline contain every pin?
print("skipped:", collections.Counter(c.get("Type") for c in comps.values() if c.get("Type")), 
      [c.findtext("RefDes") for c in comps.values() if c.get("Type")])
via = next(c for c in comps.values() if c.get("Type")=="Via")
print("sample via", via.attrib, [x.attrib for x in via.findall('./Pads/Pad')])
xs=[p[0] for p in board.outline]; ys=[p[1] for p in board.outline]
outside=[(pt.name,pn.number,round(pn.x/scale,2),round(pn.y/scale,2)) for pt in board.parts for pn in pt.pins if not(min(xs)<=pn.x<=max(xs) and min(ys)<=pn.y<=max(ys))]
print("outline bbox mm", min(xs)/scale,min(ys)/scale,max(xs)/scale,max(ys)/scale, "pins outside bbox:", outside)

# Output must satisfy the viewer-parser rules; names must be single tokens.
fmt, ps, pins = t.read_brd(d.to_brd(board))
print("brd ok:", len(fmt), len(ps), len(pins), "dup refdes:", [k for k,v in collections.Counter(p[0] for p in ps).items() if v>1])
print("part kinds:", collections.Counter(p[1] for p in ps))
print("nets (top by pins):", collections.Counter(p[4] for p in pins).most_common(8))
print("parts:", " ".join(p[0] for p in ps))
print("names with non-ascii:", [p[0] for p in ps if not p[0].isascii()], [n for n in {p[4] for p in pins} if not n.isascii()])
print("sample pin names:", [(pn.number,pn.name) for pn in board.parts[0].pins])
