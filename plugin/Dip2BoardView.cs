// DipTrace PCB Layout plugin: writes OpenBoardView files (.brd and .bvr) from the open board.
//
// DipTrace passes the board to the plugin as XML (plugin_exchange.xml, argv[1]). This plugin
// is export-only: it never changes that file, and settings.xml sets ImpMode=None, so nothing
// goes back into the design.
//
// This is a C# port of dip2boardview.py and must stay output-identical to it. It follows the
// same steps in the same order, including Python's rounding rules.
//
// Usage:
//   Dip2BoardView.exe <plugin_exchange.xml>             asks where to save, then writes both files
//   Dip2BoardView.exe <board.xml> --out <folder\name>   writes name.brd and name.bvr, no UI
//
// Build: see build.ps1 (C# 5, .NET Framework 4, which is part of Windows).

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Numerics;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Forms;
using System.Xml;
using System.Xml.Linq;

[assembly: System.Reflection.AssemblyTitle("DipTrace to OpenBoardView export plugin")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]

namespace Dip2BoardView
{
    class ConversionError : Exception
    {
        public ConversionError(string message) : base(message) { }
    }

    struct P
    {
        public double X, Y;
        public P(double x, double y) { X = x; Y = y; }
        public bool Same(P o) { return X == o.X && Y == o.Y; }
    }

    struct IP
    {
        public long X, Y;
        public IP(long x, long y) { X = x; Y = y; }
    }

    class Pin
    {
        public string Number, Name, Side, Net;
        public double X, Y, Radius;
    }

    class Part
    {
        public string Name, Side;
        public bool Smd;
        public double X, Y;
        public List<Pin> Pins = new List<Pin>();
    }

    class Board
    {
        public List<Part> Parts;
        public List<P> Outline;
        public List<string> Warnings;
    }

    // A dictionary that, like a Python dict, accepts a missing (null) key and keeps the
    // position of a key's first insertion while the last value wins.
    class PyDict<T>
    {
        const string NullKey = "\u0000<None>";
        readonly Dictionary<string, T> map = new Dictionary<string, T>(StringComparer.Ordinal);
        public readonly List<string> Keys = new List<string>();

        static string K(string key) { return key ?? NullKey; }

        public void Set(string key, T value)
        {
            if (!map.ContainsKey(K(key))) Keys.Add(key);
            map[K(key)] = value;
        }

        public bool TryGet(string key, out T value) { return map.TryGetValue(K(key), out value); }
        public bool Has(string key) { return map.ContainsKey(K(key)); }
        public T this[string key] { get { return map[K(key)]; } }
        public int Count { get { return Keys.Count; } }
    }

    static class Converter
    {
        public const string NoNet = "UNCONNECTED_PIN";
        static readonly double ArcStep = 5 * (Math.PI / 180.0);  // CPython math.radians(5)
        const double Tau = 6.283185307179586;
        static readonly HashSet<string> SkippedTypes = new HashSet<string> { "Via", "MtHole", "Fiducial" };
        static readonly Regex Spaces = new Regex(@"\s+");
        static readonly Regex Digits = new Regex("([0-9]+)");

        static double UnitsToMil(string units)
        {
            switch (units)
            {
                case "mm": return 1 / 0.0254;
                case "inch": return 1000.0;
                case "mil": return 1.0;
                default: throw new ConversionError("Unsupported or missing Units=" + Repr(units) + ".");
            }
        }

        static string Repr(string s) { return s == null ? "None" : "'" + s + "'"; }
        static string Str(string s) { return s ?? "None"; }

        static string Attr(XElement e, string name)
        {
            XAttribute a = e.Attribute(name);
            return a == null ? null : a.Value;
        }

        static string Attr(XElement e, string name, string fallback) { return Attr(e, name) ?? fallback; }

        static double Real(XElement e, string name)
        {
            string raw = Attr(e, name);
            if (raw == null) return 0.0;
            double value;
            if (!double.TryParse(raw.Replace(",", ".").Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out value))
                throw new ConversionError("Could not read " + name + "=" + Repr(raw) + ".");
            return value;
        }

        static string Clean(string text)
        {
            return Spaces.Replace((text ?? "").Trim(), "_");
        }

        static string ChildText(XElement e, string tag)
        {
            XElement c = e.Element(tag);
            if (c == null) return "";
            // Like ElementTree's findtext: only the text before the first child element.
            var text = new StringBuilder();
            foreach (var node in c.Nodes())
            {
                if (node is XElement) break;
                var t = node as XText;  // XCData is an XText too
                if (t != null) text.Append(t.Value);
            }
            return Clean(text.ToString());
        }

        static bool Enabled(XElement e) { return Attr(e, "Enabled", "Y") != "N"; }

        static IEnumerable<XElement> Children(XElement e, string a, string b)
        {
            return e.Elements(a).Elements(b);
        }

        static double PyMod(double a, double b)
        {
            double r = a % b;
            if (r != 0 && (r < 0) != (b < 0)) r += b;
            return r;
        }

        static double Hypot(double x, double y) { return Math.Sqrt(x * x + y * y); }

        public static List<P> TessellateArc(P a, P mid, P b)
        {
            double d = 2 * (a.X * (mid.Y - b.Y) + mid.X * (b.Y - a.Y) + b.X * (a.Y - mid.Y));
            if (Math.Abs(d) < 1e-9) return new List<P> { b };
            double a2 = a.X * a.X + a.Y * a.Y, m2 = mid.X * mid.X + mid.Y * mid.Y, b2 = b.X * b.X + b.Y * b.Y;
            double cx = (a2 * (mid.Y - b.Y) + m2 * (b.Y - a.Y) + b2 * (a.Y - mid.Y)) / d;
            double cy = (a2 * (b.X - mid.X) + m2 * (a.X - b.X) + b2 * (mid.X - a.X)) / d;
            double start = Math.Atan2(a.Y - cy, a.X - cx);
            double through = Math.Atan2(mid.Y - cy, mid.X - cx);
            double end = Math.Atan2(b.Y - cy, b.X - cx);
            double ccwToMid = PyMod(through - start, Tau);
            double ccwToEnd = PyMod(end - start, Tau);
            double toMid, sweep;
            if (ccwToMid <= ccwToEnd) { toMid = ccwToMid; sweep = ccwToEnd; }
            else { toMid = ccwToMid - Tau; sweep = ccwToEnd - Tau; }
            double radius = Hypot(a.X - cx, a.Y - cy);

            var result = new List<P>();
            Run(result, cx, cy, radius, start, toMid);
            result.Add(mid);
            Run(result, cx, cy, radius, start + toMid, sweep - toMid);
            result.Add(b);
            return result;
        }

        static void Run(List<P> into, double cx, double cy, double radius, double from, double span)
        {
            int steps = Math.Max(1, (int)Math.Ceiling(Math.Abs(span) / ArcStep));
            for (int i = 1; i < steps; i++)
            {
                double t = from + span * i / steps;
                into.Add(new P(cx + radius * Math.Cos(t), cy + radius * Math.Sin(t)));
            }
        }

        static List<P> Close(List<P> contour)
        {
            if (!contour[contour.Count - 1].Same(contour[0])) contour.Add(contour[0]);
            return contour;
        }

        static List<P> OutlineContour(List<XElement> points, double scale)
        {
            var xy = points.Select(p => new P(Real(p, "X") * scale, Real(p, "Y") * scale)).ToList();
            var arc = points.Select(p => Attr(p, "Arc", "N") == "Y").ToList();
            int n = xy.Count;
            int start = -1;
            for (int k = 0; k < n; k++) if (!arc[k]) { start = k; break; }
            if (start < 0) throw new ConversionError("The board outline has only arc midpoints, so it cannot be read.");
            var contour = new List<P> { xy[start] };
            int consumed = 1;
            int i = (start + 1) % n;
            while (consumed < n)
            {
                if (arc[i])
                {
                    int end = (i + 1) % n;
                    contour.AddRange(TessellateArc(contour[contour.Count - 1], xy[i], xy[end]));
                    i = (i + 2) % n;
                    consumed += 2;
                }
                else
                {
                    contour.Add(xy[i]);
                    i = (i + 1) % n;
                    consumed += 1;
                }
            }
            return Close(contour);
        }

        static List<P> CutoutContour(XElement shape, double scale, List<string> warnings)
        {
            var xy = shape.Elements("Points").Elements().Select(p => new P(Real(p, "X") * scale, Real(p, "Y") * scale)).ToList();
            string kind = Attr(shape, "Type");
            if ((kind == "Polygon" || kind == "Polyline") && xy.Count >= 3) return Close(xy);
            if ((kind == "Rectangle" || kind == "FillRect" || kind == "Obround" || kind == "FillObround") && xy.Count == 2)
            {
                double x1 = xy[0].X, y1 = xy[0].Y, x2 = xy[1].X, y2 = xy[1].Y;
                return Close(new List<P> { new P(x1, y1), new P(x2, y1), new P(x2, y2), new P(x1, y2) });
            }
            warnings.Add("Skipped a board cutout of unsupported type " + Repr(kind) + ".");
            return new List<P>();
        }

        public static Board ParseBoard(XElement root)
        {
            if (root.Name.LocalName != "Source" || Attr(root, "Type") != "DipTrace-PCB")
                throw new ConversionError("This is not a DipTrace PCB XML file (root Type=" + Repr(Attr(root, "Type")) + ").");
            double scale = UnitsToMil(Attr(root, "Units"));
            XElement boardNode = root.Element("Board");
            if (boardNode == null) throw new ConversionError("The file has no <Board> section.");

            // The design cache nests the pattern library, so search at any depth.
            var patterns = new PyDict<XElement>();
            foreach (var p in root.DescendantsAndSelf("Pattern"))
                if (!string.IsNullOrEmpty(Attr(p, "PatternStyle"))) patterns.Set(Attr(p, "PatternStyle"), p);
            var padStyles = new PyDict<XElement>();
            foreach (var s in root.DescendantsAndSelf("PadStyle")) padStyles.Set(Attr(s, "Name"), s);
            var nets = new PyDict<string>();
            foreach (var net in Children(boardNode, "Nets", "Net")) nets.Set(Attr(net, "Id"), ChildText(net, "Name"));

            var warnings = new List<string>();
            var parts = new List<Part>();
            foreach (var component in Children(boardNode, "Components", "Component"))
            {
                if (!Enabled(component) || SkippedTypes.Contains(Attr(component, "Type") ?? "")) continue;
                Part part = ParseComponent(component, patterns, padStyles, nets, scale, warnings);
                if (part != null) parts.Add(part);
            }
            if (parts.Count == 0) throw new ConversionError("No components with pads were found.");

            var outline = new List<P>();
            XElement outlineNode = boardNode.Element("BoardOutline");
            var points = outlineNode != null && Enabled(outlineNode)
                ? outlineNode.Elements("Points").Elements().ToList() : new List<XElement>();
            if (points.Count >= 3) outline.AddRange(OutlineContour(points, scale));
            else
            {
                warnings.Add("No board outline was found, so a rectangle around the pins is used instead.");
                outline.AddRange(PinBoundsRectangle(parts));
            }
            foreach (var shape in Children(boardNode, "Shapes", "Shape"))
                if (Attr(shape, "Layer") == "Board Cutout" && Enabled(shape))
                    outline.AddRange(CutoutContour(shape, scale, warnings));

            return new Board { Parts = parts, Outline = outline, Warnings = warnings };
        }

        static Part ParseComponent(XElement component, PyDict<XElement> patterns, PyDict<XElement> padStyles,
                                   PyDict<string> nets, double scale, List<string> warnings)
        {
            string name = ChildText(component, "RefDes");
            if (name == "") name = "PAD_" + Str(Attr(component, "Id"));
            XElement pattern;
            if (!patterns.TryGet(Attr(component, "PatternStyle"), out pattern))
                throw new ConversionError(name + ": footprint " + Repr(Attr(component, "PatternStyle")) + " is not in the file.");

            var footprintPads = Children(pattern, "Pads", "Pad").ToList();
            var byId = new PyDict<XElement>();
            foreach (var p in footprintPads) byId.Set(Attr(p, "Id"), p);
            var placedPads = Children(component, "Pads", "Pad").ToList();
            if (footprintPads.Count == 0) return null;  // mechanical part with nothing to probe

            if (placedPads.Count > 0 && !placedPads.All(p => byId.Has(Attr(p, "Id"))))
            {
                if (placedPads.Count != footprintPads.Count)
                    throw new ConversionError(name + ": placed pads do not match the footprint pads.");
                warnings.Add(name + ": pad Ids differ from the footprint, so pads were matched by order.");
                byId = new PyDict<XElement>();
                for (int k = 0; k < placedPads.Count; k++) byId.Set(Attr(placedPads[k], "Id"), footprintPads[k]);
            }

            var netOf = new PyDict<string>();
            foreach (var p in placedPads) netOf.Set(Attr(p, "Id"), Attr(p, "NetId", "-1"));
            double x0 = Real(component, "X"), y0 = Real(component, "Y");
            double angle = Real(component, "Angle");
            double cosA = Math.Cos(angle), sinA = Math.Sin(angle);
            bool bottom = Attr(component, "Side", "Top") == "Bottom";

            var pads = new List<KeyValuePair<string, XElement>>();
            if (netOf.Count > 0) foreach (var id in netOf.Keys) pads.Add(new KeyValuePair<string, XElement>(id, byId[id]));
            else foreach (var p in footprintPads) pads.Add(new KeyValuePair<string, XElement>(Attr(p, "Id"), p));

            var part = new Part { Name = name, Side = bottom ? "B" : "T", X = x0 * scale, Y = y0 * scale };
            bool anySurface = false;
            foreach (var entry in pads)
            {
                XElement pad = entry.Value;
                XElement style;
                if (!padStyles.TryGet(Attr(pad, "Style"), out style))
                {
                    style = null;
                    warnings.Add(name + ": pad style " + Repr(Attr(pad, "Style")) + " is missing; treated as a surface pad.");
                }
                bool through = style != null && Attr(style, "Type") == "Through";
                anySurface = anySurface || !through;

                // DipTrace's documented placement law. Flip flags are already baked into the footprint.
                double px = Real(pad, "X"), py = Real(pad, "Y");
                if (bottom) px = -px;
                double bx = x0 + px * cosA - py * sinA;
                double by = y0 + px * sinA + py * cosA;

                string side;
                if (through) side = "O";
                else
                {
                    bool localBottom = Attr(pad, "Side", "Top") == "Bottom";
                    side = bottom != localBottom ? "B" : "T";
                }

                string number = ChildText(pad, "Number");
                if (number == "") number = Str(entry.Key);
                string netId, net;
                if (!netOf.TryGet(entry.Key, out netId)) netId = "-1";
                if (!nets.TryGet(netId, out net) || net == "") net = NoNet;
                part.Pins.Add(new Pin
                {
                    Number = number, Name = ChildText(pad, "Note"),
                    X = bx * scale, Y = by * scale, Radius = PadRadius(style, scale), Side = side, Net = net
                });
            }
            part.Smd = anySurface;
            // Viewers number .brd pins by file order, so match the pad numbers where possible.
            part.Pins = part.Pins.OrderBy(pin => pin.Number, NaturalComparer.Instance).ToList();  // stable, like Python
            return part;
        }

        static double PadRadius(XElement style, double scale)
        {
            XElement stack = style == null ? null : style.Element("MainStack");
            if (stack == null) return 10.0;
            return Math.Max(Math.Min(Real(stack, "Width"), Real(stack, "Height")) * scale / 2, 1.0);
        }

        static List<P> PinBoundsRectangle(List<Part> parts)
        {
            var pins = parts.SelectMany(p => p.Pins).ToList();
            const double margin = 100.0;
            double x1 = pins.Min(p => p.X) - margin, y1 = pins.Min(p => p.Y) - margin;
            double x2 = pins.Max(p => p.X) + margin, y2 = pins.Max(p => p.Y) + margin;
            return Close(new List<P> { new P(x1, y1), new P(x2, y1), new P(x2, y2), new P(x1, y2) });
        }

        // Whole viewer units (1 unit = 1 mil), with the board origin moved to 0,0.
        class Grid
        {
            readonly double x0, y0;
            public Grid(Board board)
            {
                var pins = board.Parts.SelectMany(p => p.Pins).ToList();
                x0 = board.Outline.Select(p => p.X).Concat(pins.Select(p => p.X)).Min();
                y0 = board.Outline.Select(p => p.Y).Concat(pins.Select(p => p.Y)).Min();
            }
            // Math.Round rounds halves to even, like Python's round().
            public IP At(double x, double y) { return new IP((long)Math.Round(x - x0), (long)Math.Round(y - y0)); }
        }

        static List<IP> Dedupe(IEnumerable<IP> points)
        {
            var result = new List<IP>();
            foreach (var p in points)
                if (result.Count == 0 || p.X != result[result.Count - 1].X || p.Y != result[result.Count - 1].Y) result.Add(p);
            return result;
        }

        static int CodePoints(string s)
        {
            int n = 0;
            for (int i = 0; i < s.Length; i++) if (!char.IsLowSurrogate(s[i])) n++;
            return n;
        }

        static string I(long v) { return v.ToString(CultureInfo.InvariantCulture); }

        public static string ToBrd(Board board)
        {
            var grid = new Grid(board);
            var outline = Dedupe(board.Outline.Select(p => grid.At(p.X, p.Y)));
            var allPins = board.Parts.SelectMany(p => p.Pins).ToList();
            var lines = new List<string>
            {
                "str_length:",
                I(board.Parts.Sum(p => CodePoints(p.Name) + 1)) + " " + I(allPins.Sum(p => CodePoints(p.Net) + 1)),
                "var_data:",
                I(outline.Count) + " " + I(board.Parts.Count) + " " + I(allPins.Count) + " 0 0 0",
                "Format:",
            };
            foreach (var p in outline) lines.Add(I(p.X) + " " + I(p.Y));
            lines.Add("Parts:");
            int endOfPins = 0;
            foreach (var part in board.Parts)
            {
                endOfPins += part.Pins.Count;
                int kind = part.Smd ? (part.Side == "T" ? 5 : 10) : (part.Side == "T" ? 1 : 2);
                lines.Add(part.Name + " " + I(kind) + " " + I(endOfPins));
            }
            lines.Add("Pins:");
            for (int index = 0; index < board.Parts.Count; index++)
                foreach (var pin in board.Parts[index].Pins)
                {
                    var xy = grid.At(pin.X, pin.Y);
                    lines.Add(I(xy.X) + " " + I(xy.Y) + " -99 " + I(index + 1) + " " + pin.Net);  // -99: no test probe
                }
            lines.Add("Nails:");
            return string.Join("\n", lines) + "\n";
        }

        public static string ToBvr(Board board)
        {
            var grid = new Grid(board);
            var lines = new List<string> { "BVRAW_FORMAT_3" };
            foreach (var part in board.Parts)
            {
                var o = grid.At(part.X, part.Y);
                lines.Add("PART_NAME " + part.Name);
                lines.Add("   PART_SIDE " + part.Side);
                lines.Add("   PART_ORIGIN " + I(o.X) + " " + I(o.Y));
                lines.Add("   PART_MOUNT " + (part.Smd ? "SMD" : "THROUGH"));
                for (int index = 0; index < part.Pins.Count; index++)
                {
                    var pin = part.Pins[index];
                    var xy = grid.At(pin.X, pin.Y);
                    lines.Add("   PIN_ID " + I(index + 1));
                    lines.Add("      PIN_NUMBER " + pin.Number);
                    if (pin.Name != "") lines.Add("      PIN_NAME " + pin.Name);
                    lines.Add("      PIN_SIDE " + pin.Side);
                    lines.Add("      PIN_ORIGIN " + I(xy.X - o.X) + " " + I(xy.Y - o.Y));  // relative to PART_ORIGIN
                    lines.Add("      PIN_RADIUS " + OneDecimal(pin.Radius));
                    lines.Add("      PIN_NET " + pin.Net);
                    lines.Add("   PIN_END");
                }
                lines.Add("PART_END");
            }
            var outline = Dedupe(board.Outline.Select(p => grid.At(p.X, p.Y)));
            lines.Add("OUTLINE_POINTS " + string.Join(" ", outline.Select(p => I(p.X) + " " + I(p.Y))));
            return string.Join("\n", lines) + "\n";
        }

        // Python's f"{v:.1f}": round the exact binary value, halves to even. Radius is always >= 1.
        static string OneDecimal(double v)
        {
            long bits = BitConverter.DoubleToInt64Bits(v);
            int exp = (int)((bits >> 52) & 0x7FF);
            long frac = bits & 0xFFFFFFFFFFFFFL;
            BigInteger mantissa = exp == 0 ? frac : frac | (1L << 52);
            int e = (exp == 0 ? 1 : exp) - 1075;  // v = mantissa * 2^e
            BigInteger tenths;
            if (e >= 0) tenths = mantissa * 10 * BigInteger.Pow(2, e);
            else
            {
                BigInteger num = mantissa * 10, den = BigInteger.Pow(2, -e);
                BigInteger rem;
                tenths = BigInteger.DivRem(num, den, out rem);
                int cmp = (rem * 2).CompareTo(den);
                if (cmp > 0 || (cmp == 0 && !tenths.IsEven)) tenths += 1;
            }
            return (tenths / 10).ToString(CultureInfo.InvariantCulture) + "." + (tenths % 10).ToString(CultureInfo.InvariantCulture);
        }

        public static string Summary(Board board, IEnumerable<string> written)
        {
            var pins = board.Parts.SelectMany(p => p.Pins).ToList();
            var lines = new List<string>
            {
                board.Parts.Count + " parts, " + pins.Count + " pins, " + pins.Count(p => p.Net != NoNet) + " connected to a net"
            };
            lines.AddRange(written.Select(w => "Wrote " + w));
            lines.AddRange(board.Warnings.Select(w => "Warning: " + w));
            return string.Join("\n", lines);
        }

        // Python's natural_key: digit runs compare as numbers, other runs by code point.
        class NaturalComparer : IComparer<string>
        {
            public static readonly NaturalComparer Instance = new NaturalComparer();

            static List<string> Split(string s)
            {
                return Digits.Split(s).Where(t => t.Length > 0).ToList();
            }

            static bool IsNumber(string t) { return t[0] >= '0' && t[0] <= '9'; }

            static int CompareNumbers(string a, string b)
            {
                a = a.TrimStart('0'); b = b.TrimStart('0');
                if (a.Length != b.Length) return a.Length.CompareTo(b.Length);
                return string.CompareOrdinal(a, b);
            }

            public int Compare(string x, string y)
            {
                var a = Split(x); var b = Split(y);
                for (int i = 0; i < Math.Min(a.Count, b.Count); i++)
                {
                    bool na = IsNumber(a[i]), nb = IsNumber(b[i]);
                    int c;
                    if (na != nb) c = na ? -1 : 1;
                    else if (na) c = CompareNumbers(a[i], b[i]);
                    else c = Math.Sign(string.CompareOrdinal(a[i], b[i]));
                    if (c != 0) return c;
                }
                return a.Count.CompareTo(b.Count);
            }
        }
    }

    static class Program
    {
        const string Title = "Export to OpenBoardView";
        static readonly UTF8Encoding Utf8 = new UTF8Encoding(false);

        static string StateFile
        {
            get
            {
                return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                    "DipTrace", "Dip2BoardView", "last-output.txt");
            }
        }

        [STAThread]
        static int Main(string[] args)
        {
            bool headless = args.Length == 3 && args[1] == "--out";
            try
            {
                if (args.Length != 1 && !headless)
                {
                    if (args.Length == 0)
                        MessageBox.Show("This is a DipTrace PCB Layout plugin. Run it from Tools > Plugins.", Title);
                    return 2;
                }
                Board board = Converter.ParseBoard(Load(args[0]));
                if (headless) { Write(board, args[2]); return 0; }

                Application.EnableVisualStyles();
                string stem = AskForOutput();
                if (stem == null) return 0;
                var written = Write(board, stem);
                Remember(stem);
                MessageBox.Show(Converter.Summary(board, written), Title, MessageBoxButtons.OK, MessageBoxIcon.Information);
                return 0;
            }
            catch (Exception ex)
            {
                string log = WriteLog(ex);
                if (headless)
                {
                    Console.Error.WriteLine(ex.Message);
                }
                else
                {
                    string text = ex is ConversionError || ex is IOException || ex is UnauthorizedAccessException
                        ? ex.Message : "Unexpected error: " + ex.Message;
                    if (log != null) text += "\n\nDetails: " + log;
                    MessageBox.Show(text, Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
                return 1;
            }
        }

        static XElement Load(string path)
        {
            try { return XDocument.Load(path).Root; }
            catch (XmlException ex) { throw new ConversionError(Path.GetFileName(path) + " is not valid XML: " + ex.Message); }
        }

        static List<string> Write(Board board, string stem)
        {
            string brd = stem + ".brd", bvr = stem + ".bvr";
            File.WriteAllText(brd, Converter.ToBrd(board), Utf8);
            File.WriteAllText(bvr, Converter.ToBvr(board), Utf8);
            return new List<string> { brd, bvr };
        }

        // DipTrace does not tell plugins where the project is saved, so ask once and remember.
        static string AskForOutput()
        {
            string last = null;
            try { if (File.Exists(StateFile)) last = File.ReadAllText(StateFile, Utf8).Trim(); }
            catch (IOException) { }

            using (var owner = new Form { ShowInTaskbar = true, Text = Title, Opacity = 0, StartPosition = FormStartPosition.CenterScreen })
            using (var dialog = new SaveFileDialog())
            {
                dialog.Title = Title + " (writes .brd and .bvr)";
                dialog.Filter = "OpenBoardView board (*.brd + *.bvr)|*.brd";
                dialog.DefaultExt = "brd";
                dialog.AddExtension = true;
                dialog.OverwritePrompt = true;
                if (!string.IsNullOrEmpty(last))
                {
                    dialog.InitialDirectory = Path.GetDirectoryName(last);
                    dialog.FileName = Path.GetFileName(last);
                }
                owner.Show();
                owner.Activate();
                if (dialog.ShowDialog(owner) != DialogResult.OK) return null;
                string chosen = dialog.FileName;
                return Path.Combine(Path.GetDirectoryName(chosen), Path.GetFileNameWithoutExtension(chosen));
            }
        }

        static void Remember(string stem)
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(StateFile));
                File.WriteAllText(StateFile, stem + ".brd", Utf8);
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }

        static string WriteLog(Exception ex)
        {
            string[] folders =
            {
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "DipTrace", "PluginLogs"),
                Path.Combine(Path.GetTempPath(), "DipTrace", "PluginLogs"),
            };
            foreach (var folder in folders)
            {
                try
                {
                    Directory.CreateDirectory(folder);
                    string path = Path.Combine(folder, "Dip2BoardView.log");
                    File.WriteAllText(path, DateTime.Now.ToString("s") + "\n" + ex, Utf8);
                    return path;
                }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
            return null;
        }
    }
}
