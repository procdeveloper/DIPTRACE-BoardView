# OpenBoardView settings

Read from the OpenBoardView source on the `master` branch, not tested in the program.
Installed versions may differ. Items marked *inferred* come from reading how the code
behaves rather than from a stated value.

## Per-board settings: `<board>.conf`

Stored beside the board, with the same name: `foo.brd` uses `foo.conf`. Edit them under
**File > Board Settings**. Relative paths are resolved from the `.conf` file's folder.

*Inferred:* OpenBoardView only uses a `.conf` that already exists or one you save from
Board Settings. Opening a board doesn't create one.

### Schematic PDF

| Key | Default | Meaning |
|---|---|---|
| `PDFFilePath` | Board name with `.pdf` | Schematic PDF to open in the PDF viewer |

If the key is absent, `foo.brd` looks for `foo.pdf` beside it, so a PDF with a matching
name needs no `.conf` at all.

### Background images

Each key exists with a `Top` and a `Bottom` prefix. For example, `TopImageFile` and
`BottomImageFile`.

| Key suffix | Type | Default | Meaning |
|---|---|---|---|
| `ImageFile` | Path | None | Image shown behind that side of the board |
| `ImageOffsetX`, `ImageOffsetY` | Integer | 0 | Position, in board units |
| `ImageScalingX`, `ImageScalingY` | Decimal | 1.0 | Scale |
| `ImageMirrorX`, `ImageMirrorY` | `true`/`false` | `false` | Flip horizontally or vertically |
| `ImageTransparency` | 0.0 to 1.0 | 0.0 | 0 is opaque |

There is no rotation setting.

### Example

```text
PDFFilePath = schematics/foo.pdf
TopImageFile = images/foo-top.png
TopImageOffsetX = 0
TopImageOffsetY = 0
TopImageScalingX = 1.000000
TopImageScalingY = 1.000000
TopImageMirrorX = false
TopImageMirrorY = false
TopImageTransparency = 0.000000
```

## Program-wide settings: `obv.conf`

*Inferred location on Windows:* `%APPDATA%\OpenBoardView\obv.conf`. The `-c <file>` command
line option uses a different file. Edit these under **File > Program Preferences**,
**Colour Preferences** and **Keyboard Preferences**, or from the **View** menu.

| Group | Keys |
|---|---|
| PDF viewer (Windows) | `pdfSoftwarePath` (default `SumatraPDF.exe`) |
| Window and text | `dpi`, `windowX`, `windowY`, `renderer`, `fontName`, `fontSize`, `slowCPU`, `showFPS` |
| Info panel | `showInfoPanel`, `infoPanelWidth`, `infoPanelCenterZoomNets`, `infoPanelSelectPartsOnNet` |
| Zoom, pan, flip | `zoomFactor`, `zoomModifier`, `panFactor`, `panModifier`, `flipMode`, `partZoomScaleOutFactor`, `centerZoomSearchResults` |
| What is drawn | `showPins`, `showPosition`, `showNetWeb`, `showAnnotations`, `showBackgroundImage`, `fillParts`, `showPartName`, `showPinName`, `boardFill`, `boardFillSpacing`, `netWebThickness`, `annotationBoxSize`, `annotationBoxOffset` |
| Pins | `pinSizeThresholdLow`, `pinShapeCircle`, `pinShapeSquare`, `pinHalo`, `pinHaloDiameter`, `pinHaloThickness`, `pinSelectMasks`, `pinA1threshold` |
| Encrypted formats | `FZKey`, `CAEKey`, `XZZPCBKey` |
| Colours (`0xRRGGBBAA`) | `colorTheme` (`light` or `dark`), plus one key per colour, such as `backgroundColor`, `boardOutlineColor`, `partOutlineColor`, `pinDefaultColor`, `pinGroundColor`, `pinNotConnectedColor`, `pinSameNetColor`, `pinHaloColor`, `pinNetWebColor` |
| Keyboard | `KeyBinding<Name>`, such as `KeyBindingFlip` or `KeyBindingSearch` |

Sources: `PDFBridge/PDFFile.cpp`, `GUI/BackgroundImage.cpp`, `GUI/Config.cpp`,
`GUI/ColorScheme.cpp`, `UI/Keyboard/KeyBindings.cpp` and `BoardView.cpp`, all under
`src/openboardview/` in [the OpenBoardView repository](https://github.com/OpenBoardView/OpenBoardView).
