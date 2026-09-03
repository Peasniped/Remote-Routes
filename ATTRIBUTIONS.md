# Attributions

Remote Routes itself is licensed under the [GNU General Public License v3.0](LICENSE).
The third-party assets bundled with it are listed below and remain under their own
licenses.

## Icons

All SVG icons in [`static/icons/`](static/icons/) were obtained from
**[SVG Repo](https://www.svgrepo.com/)**, which mirrors icons from many different
collections under a mix of licenses. Collection, author and license for each icon are
listed below.

| File | Used for | Source | Collection | Author | License |
|---|---|---|---|---|---|
| `bring-to-front-svgrepo.svg` | "Bring to front" card hover + context menu | [509766](https://www.svgrepo.com/svg/509766/bring-to-front) | Zest Interface Icons | zest | MIT |
| `close-svgrepo.svg` | "Close connection(s)" context menu | [500512](https://www.svgrepo.com/svg/500512/close-bold) | Element Plus Line Interface Icons | element-plus | MIT |
| `delete-svgrepo.svg` | "Delete" context menu | [488148](https://www.svgrepo.com/svg/488148/delete) | Neuicons Oval Solid Icons | Neuicons | MIT |
| `edit-svgrepo.svg` | "Edit" context menu | [502640](https://www.svgrepo.com/svg/502640/edit-1) | Kalai Oval Interface Icons | Ananthanath A X Kalaiism | Public Domain |
| `globe-europe-solid-svgrepo-com.svg` | WEB host open actions | [314050](https://www.svgrepo.com/svg/314050/globe-europe-solid) | Line Awesome | Icons8 | MIT |
| `locate-svgrepo.svg` | "Locate window(s)" context menu | [510051](https://www.svgrepo.com/svg/510051/locate) | Zest Interface Icons | zest | MIT |
| `move-here-svgrepo.svg` | "Move to this monitor" context menu | [470984](https://www.svgrepo.com/svg/470984/arrow-circle-broken-down-left) | Ui Oval Interface Icons | SVG Repo (uploader) | CC0 |
| `plus-square-on-square-svgrepo-com.svg` | "Start additional connection" context menu | [437159](https://www.svgrepo.com/svg/437159/plus-square-on-square) | _TODO_ | _TODO_ | _TODO_ |
| `paperplane-svgrepo.svg` | "Connect" card hover + context menu | [352315](https://www.svgrepo.com/svg/352315/paper-plane) | Font Awesome Solid Icons | FortAwesome | **CC BY** |
| `plus-svgrepo.svg` | "Add host" toolbar button | [509386](https://www.svgrepo.com/svg/509386/plus) | Nataicons Oval Tiny Line Icons | afnizarnur | MIT |
| `settings-svgrepo.svg` | "Settings" toolbar button | [498931](https://www.svgrepo.com/svg/498931/settings2) | Uxwb Bold Line Icons | UXWB | **GPL** |

Icons are recolored at runtime by `_load_icon()` in [`src/app.py`](src/app.py) via string
replacement on the SVG source. The source files themselves are unmodified.

> **Note on `plus-square-on-square-svgrepo-com.svg`** — this icon replaced an earlier
> `new-window` icon whose SVG Repo page could not be located again. The source URL above
> is inferred from the filename and has not been confirmed against the page, so its
> collection, author and licence are still unfilled. This is the last remaining
> attribution gap — worth closing before the repository goes public.

### Licence obligations

Most of the set is MIT, CC0 or Public Domain, but three rows carry real obligations:

- **`paperplane-svgrepo.svg` — CC BY (Font Awesome, FortAwesome).** Attribution is
  required and must reach the *end user of the application*, not just readers of this
  repository. This file therefore has to be distributed alongside the built application
  (see below), or the credit must be surfaced in-app.
- **`settings-svgrepo.svg` — GPL (UXWB).** Copyleft, and compatible with this project's
  GPL-3.0 licence. Worth knowing that it would become a blocker if Remote Routes were
  ever relicensed to something more permissive; swapping this one icon would remove that
  constraint.
- **The MIT rows** technically require their permission notice to travel with
  "substantial portions" of the work. Shipping this file with the application satisfies
  that.

**Practical consequence for packaging:** whichever distribution method is chosen (see the
`Propper installation/distribution method` item in `ToDo`), this file — or an in-app
"About / Credits" view built from it — must be included in the distributed artifact. A
bare `.exe` with no accompanying credits would not satisfy the CC BY row.

## Logo

`static/logo.png` and `static/logo.ico` are original artwork created for this project.
They are covered by the project's own licence and require no third-party attribution.

## Dependencies

- **[PySide6](https://doc.qt.io/qtforpython/)** — Qt for Python, licensed under the
  [LGPL v3](https://www.qt.io/licensing/). Used as an unmodified, dynamically-linked
  library.
