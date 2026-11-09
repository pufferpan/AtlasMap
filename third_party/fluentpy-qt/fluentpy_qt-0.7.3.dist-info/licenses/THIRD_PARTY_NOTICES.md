# Third-Party Notices

## Table interaction reference

- Reference: https://qfluentwidgets.com/zh/pages/components/tableview/
- Usage: publicly visible table organization and interaction categories only (item/model interfaces, ordinary/rounded/lined rows and right-click selection).
- FluentPy implements these independently using Qt's public model/view APIs, its existing controls, ActionMenu and theme tokens. No external source, stylesheet, screenshot, demonstration wording or data is included.

## Fluent window interaction reference

- Reference: https://qfluentwidgets.com/zh/pages/components/fluentwindow/
- Usage: public window-organization and interaction categories only (page navigation, history, responsive layouts, settings placement and title-bar extension).
- FluentPy implements these independently with its existing navigation and controls, ordinary Qt layouts, and Qt system move/resize APIs. Native window chrome remains the default; optional Windows frame-material requests keep the Qt client area opaque.
- No source code, screenshots, stylesheets or example wording from this reference are included.

## Slider and menu interaction references

- References: https://qfluentwidgets.com/zh/pages/components/slider/ and https://qfluentwidgets.com/zh/pages/components/menu/
- Usage: public interaction categories only. Slider and ActionMenu are extended independently; the new tooltip/range sliders and native tray menu use Qt APIs and the project's existing UI components.
- No source code, screenshots, stylesheets or example wording from these references are included.

## Combo box interaction reference

- Reference: https://qfluentwidgets.com/zh/pages/components/combobox/
- Usage: public interaction categories only (editable, model-backed, multiple, hierarchical, transparent and font choices).
- FluentPy implements these independently using Qt models/views and its existing ActionMenu, inputs and buttons. No source code, stylesheets, screenshots or example text from this reference are included.

FluentPy may use or adapt resources from third-party open-source projects only when their license is compatible with this project.

## Microsoft Fluent UI System Icons

- Source: https://github.com/microsoft/fluentui-system-icons
- Copyright (c) 2020 Microsoft Corporation.
- License: MIT; complete text in `licenses/Microsoft-Fluent-System-Icons-LICENSE.txt`.
- Usage: bundled SVG icons for `IconButton`, examples, and future controls.
- Bundled files: `src/fluentpy/assets/icons/ic_fluent_*_24_regular.svg` (107 icons).
- Eyedropper: original Microsoft `assets/Eyedropper/SVG/ic_fluent_eyedropper_24_regular.svg`, bundled unchanged as `FluentIcon.EYEDROPPER`; download URL and checksum in `src/fluentpy/assets/icons/SOURCE.md`.
- Music Note 2: original `assets/Music Note 2/SVG/ic_fluent_music_note_2_24_regular.svg` from the official Microsoft repository, bundled unchanged as `FluentIcon.MUSIC_NOTE_2`. Its pinned source and checksum are recorded in `src/fluentpy/assets/icons/SOURCE.md`.

## Qt for Python

Qt, PySide6 and the optional PyQt6 fallback are third-party dependencies. This source project does not vendor their binaries. Their own licenses apply separately; FluentPy's MIT license does not replace them.

## Microsoft WinUI Gallery

- Source: https://github.com/microsoft/WinUI-Gallery
- License: MIT
- Usage: reference for component gallery organization and Fluent control presentation patterns.

## Microsoft WinUI

- Source: https://github.com/microsoft/microsoft-ui-xaml
- License: MIT
- Usage: reference for WinUI control behavior, theme resources, and state model where individual files are covered by the repository license. Current reference: `controls/dev/CommonStyles/Button_themeresources.xaml`.
