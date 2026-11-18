# DipTrace to boardview converter

Converts a DipTrace PCB XML export (`.dipxml`) to boardview files for OpenBoardView.
Needs Python 3.10 or newer and nothing else.

## Use

1. In DipTrace PCB Layout, export the board to DipTrace XML from the File menu.
   Native `.dip` files are binary and are not read.
2. Run the converter:

```bash
python dip2boardview.py board.dipxml
```

| Option | Effect |
|---|---|
| `-f brd`, `-f bvr`, `-f both` | Choose the output format (default `both`) |
| `-o FOLDER` | Output folder (default: next to the input) |
| no input file | Opens a file picker (this path has not been run yet) |

To open the schematic alongside the board, see
[docs/openboardview-settings.md](docs/openboardview-settings.md).

## DipTrace plugin

`plugin/` holds a DipTrace PCB Layout plugin that writes the `.brd` and `.bvr` directly from
the open board, with no manual XML export. It is a C# port of `dip2boardview.py` and must
produce the same bytes.

- **Install:** build it (below) or download `Dip2BoardView.zip` from
  [Releases](https://github.com/procdeveloper/DIPTRACE-BoardView/releases), then copy the `Dip2BoardView/` folder
  into `C:\Program Files\DipTrace\Plugins\Pcb\` (needs admin) and restart PCB Layout.
- **Use:** Tools > Plugins > Export to OpenBoardView. The first time, choose where to save;
  the plugin remembers the last file name in `%LOCALAPPDATA%\DipTrace\Dip2BoardView\`.
  DipTrace doesn't tell plugins where the project is saved, so it can't default to that folder.
- **How it gets the board:** DipTrace hands every plugin the live board as XML
  (`plugin_exchange.xml`) and runs its exe. `settings.xml` asks for components, nets, shapes
  and the outline, and sets `ImpMode=None`, so nothing is sent back into the design.
- **Build:** `powershell -ExecutionPolicy Bypass -File plugin\build.ps1` writes
  `plugin\Dip2BoardView\` (exe + `settings.xml`). It uses the C# compiler in .NET Framework 4,
  which is part of Windows, and the exe needs no runtime.
- **Errors** are shown in a message box and logged to
  `%LOCALAPPDATA%\DipTrace\PluginLogs\Dip2BoardView.log`.
- **Testing without DipTrace:** `Dip2BoardView.exe board.xml --out folder\name` writes
  `name.brd` and `name.bvr` with no dialog.


Tested inside PCB Layout 5.3.5.1 through [DIPTRACE-MCP](https://github.com/procdeveloper/DIPTRACE-MCP): it got
the live board from DipTrace and wrote `.brd` and `.bvr` files byte-identical to the Python
converter's, on a real board and five sample variants: arcs, a wrapped arc, no outline, a cutout,
and a half-way pad radius rounding case.

## Related projects

- [DIPTRACE-MCP](https://github.com/procdeveloper/DIPTRACE-MCP): MCP server that drives DipTrace, used to test
  the plugin inside PCB Layout.

## Output formats

| | `.brd` (Test_Link text) | `.bvr` (`BVRAW_FORMAT_3`) |
|---|---|---|
| Pin numbers | 1 to N, in file order | Real pad numbers, such as `A1` |
| Pin names | No | Yes, from the pad's note |
| Through-hole pins | Tied to the part's side, per the parser source | Marked as both sides |

Coordinates are whole units of 1 mil, with the board's lowest corner moved to 0,0.

## How the conversion works

Everything is in `dip2boardview.py`.

- **Input:** `parse_board` reads `/Source/Board`. Footprints and pad styles come from
  the library nested inside the file, matched by `PatternStyle` and `Style`.
- **Pin position:** footprint pad `(px, py)` and component `(X, Y, Angle)` give:

  ```text
  if Side == Bottom: px = -px
  x = X + px*cos(Angle) - py*sin(Angle)
  y = Y + px*sin(Angle) + py*cos(Angle)
  ```

  `Flip` and `HorzFlip` are not applied, because the exported footprint already includes them.
- **Pin side:** through-hole pads are on both sides. A surface pad follows the part's
  side, and swaps if the footprint marks it as local bottom.
- **Nets:** a pad's `NetId` decides its net. Pads with no net become `UNCONNECTED_PIN`,
  which OpenBoardView treats as not connected.
- **Outline:** arcs are flattened into short lines that pass through DipTrace's stored
  midpoint. Each contour repeats its first point, because that is how OpenBoardView finds
  the end of a contour. Cutouts are added as extra contours. With no outline, a rectangle
  around the pins is used and a warning is printed.
- **Names:** whitespace becomes `_`, because these formats separate fields with spaces.

## Limitations

- Traces, vias, mounting holes and fiducials are not included.
- `Net 2` becomes `Net_2`, so selecting `Net 2` in a schematic PDF won't find it on the board.
- OpenBoardView draws part outlines from pin positions, so footprint shapes are not exported.
- Curved or other unusual cutout shapes are skipped with a warning.

## Testing

```bash
python -m unittest -v test_dip2boardview
```

```bash
python crosscheck.py your_board.dipxml .
```

- `test_dip2boardview.py` has 20 tests on a sample board written from the spec. Its `.brd`
  checks copy the rules in OpenBoardView's parser.
- `crosscheck.py` compares converted pins with data stored separately in a real export
  (routed trace endpoints and DipTrace's per-net pad lists), so it needs a routed board.

Results on a real routed board (40 parts, 100 pins):

| Check | Compared | Result |
|---|---|---|
| Pin position vs routed trace endpoints | 133 endpoints | Worst difference 0.0001 mm |
| SMD pin side vs the trace's copper layer | 100 | No mismatches |
| Pin net vs net on those traces | 133 | No mismatches |
| Pin net vs DipTrace's per-net pad lists | 100 | No mismatches |

The output was also opened in OpenBoardView and looked right. This is the only real board
tested so far. It has straight outline edges and no cutouts, so arcs and cutouts have only
been tested on the sample board.

## Folder contents

| Path | Contents |
|---|---|
| `dip2boardview.py` | The converter |
| `plugin/` | DipTrace plugin source, `settings.xml` and build script |
| `test_dip2boardview.py`, `crosscheck.py` | Tests and the real-board check |
| `examples/sample.dipxml` | Small synthetic board (the one the tests use) to try the converter on |
| `docs/openboardview-settings.md` | OpenBoardView settings, including the schematic PDF link |

## Viewer

Get [OpenBoardView](https://github.com/OpenBoardView/OpenBoardView/releases) and, to open
schematics from it, [SumatraPDF](https://www.sumatrapdfreader.org/). OpenBoardView's default
`pdfSoftwarePath` is `SumatraPDF.exe` resolved from its own folder, so putting `SumatraPDF.exe`
beside `openboardview.exe` works with no configuration. A schematic saved as `board.pdf` beside
`board.brd` opens with no `.conf`.

## Development notes

- **Why `.dipxml`:** the XML is documented in the DipTrace install (`Docs` folder). The binary
  `.dip` is proprietary and would need reverse-engineering.
- **Why both formats:** `.brd` has the widest support, but `.bvr` keeps pad numbers and pin names
  and marks through-hole pins as both sides. Prefer `.bvr` when probing through-hole parts on the
  bottom from the top view.
- **Part outlines** are not exported: OpenBoardView ignores `PART_OUTLINE_RELATIVE` and draws
  outlines from pins.
- **Python/C# parity:** `plugin/Dip2BoardView.cs` must produce the same bytes as
  `dip2boardview.py`. Run both on the same input after changing either. Watch for Python's
  half-even rounding in `round()` and `:.1f`, Python's floored `%`, the stable sort, and
  `findtext` reading only the element's own text.
- **Untested:** the file picker (running with no input file), and arcs/cutouts on a real board.

## Sources

- DipTrace PCB XML specification: ships with DipTrace in the install's `Docs` folder
  (`DipTraceXML_Pcb_En.pdf`), not redistributed here.

OpenBoardView, read online:

- [.brd format wiki](https://www.github.com/OpenBoardView/OpenBoardView/wiki/.brd-format)
- [BRDFile.cpp](https://raw.githubusercontent.com/OpenBoardView/OpenBoardView/master/src/openboardview/FileFormats/BRDFile.cpp)
- [BVR3File.cpp](https://raw.githubusercontent.com/OpenBoardView/OpenBoardView/master/src/openboardview/FileFormats/BVR3File.cpp)
- [BRDBoard.cpp](https://raw.githubusercontent.com/OpenBoardView/OpenBoardView/master/src/openboardview/BRDBoard.cpp)
- [BoardView.cpp](https://raw.githubusercontent.com/OpenBoardView/OpenBoardView/master/src/openboardview/BoardView.cpp)

## License

MIT, see [LICENSE](LICENSE). DipTrace is a product of Novarm Ltd. and OpenBoardView is a
separate MIT-licensed project; this project is not affiliated with either.
