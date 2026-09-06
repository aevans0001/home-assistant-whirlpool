# Whirlpool laundry control — HA 2026.8.3 / lib 1.3.1 compatibility fork

Branch `compatibility/ha-2026.8.3-whirlpool-laundry-controls`, baselined at
the REAL Home Assistant Core release tag `2026.8.3` (commit
`759e4658f40b3ccb671d418b8a0ed95224bf4561`) — this is what Adam's Home
Assistant OS installation actually runs. This corrects Phase 5F, whose
`feature/whirlpool-laundry-controls` branch was baselined against a
home-assistant/core **dev** commit (`dfb49d1d...`) and library version 2.x,
neither of which matches Adam's real installation.

**The Phase 5F branch is preserved, not deleted** — see "Relationship to
Phase 5F" below.

## What changed relative to the real 2026.8.3 baseline

Verified: the `homeassistant/components/whirlpool/` directory is
byte-identical between the `dfb49d1d` dev commit Phase 5F used and the
real `2026.8.3` release tag (diffed every file - zero differences). So
this branch's `binary_sensor.py`, `button.py`, `icons.json`,
`strings.json`, and `translations/en.json` changes are exactly the ones
described in Phase 5F's own CHANGES.md - nothing about that work was
wrong, only the version label attached to it and two other things below:

- **`config_flow.py` is REVERTED to byte-identical with the 2026.8.3
  baseline.** Phase 5F's CHANGES.md claimed
  `except TimeoutError, ClientError:` was invalid Python 3 syntax and
  "fixed" it to `except (TimeoutError, ClientError):`. That claim was
  wrong: [PEP 758](https://peps.python.org/pep-0758/) ("Allow except and
  except* expressions without parentheses") was accepted and targets
  Python 3.14, which is exactly what HA 2026.8.3 runs. Under PEP 758, an
  unparenthesized multi-exception `except` clause is valid **as long as
  there is no `as` clause** - this one has none, so the original line is
  valid, correct Python 3.14 and needed no fix. This was independently
  confirmed both by fetching the PEP 758 text directly and by testing
  Python 3.13 (one version short of what Adam runs): 3.13 rejects the
  line with "multiple exception types must be parenthesized" - the exact
  Python-2-syntax-looking error that led to the incorrect Phase 5F
  diagnosis - while the PEP 758 text confirms 3.14 accepts it. This
  sandbox has no Python 3.14 interpreter available to execute directly
  (not in its package manager), so the confirmation rests on the PEP
  text plus the 3.13 comparison, not a literal 3.14 compile in this
  sandbox - Adam's own `python3 -m py_compile config_flow.py` on his
  real HAOS Python 3.14 is the authoritative check and should show no
  error. Per instruction, this is **not** filed as an HA bug and **not**
  listed as a fix in this document beyond this explanation, since it
  turned out not to be a bug at all.
- **`manifest.json` `requirements` is `["whirlpool-sixth-sense==1.3.1.post1"]`**,
  not `>=2.0.1`. See "Dependency strategy" below for why the exact pin
  and the `.post1` matter.

## Relationship to Phase 5F

`feature/whirlpool-laundry-controls` (library: `feature/api144-laundry-controls`)
remains in this repository, untouched, as forward-port reference work
against current upstream HA dev / whirlpool-sixth-sense 2.x. It is not
what Adam should install today. This compatibility branch is the one that
matches his real environment and is the one intended for local testing.
Once/if Adam upgrades past whirlpool-sixth-sense 2.x's eventual HA Core
adoption, the Phase 5F branch becomes the relevant one again.

## Dependency strategy (Home Assistant OS)

Adam's HAOS Core container should never be manually pip-installed into by
hand - that's an unsupported, non-persistent change that gets wiped on
the next Core container update, which is exactly what "do not hack the
HAOS Core container's Python environment" in the Phase 5F.1 instructions
is warning against.

Home Assistant's own supported mechanism for a custom integration
dependency that isn't (yet) the exact version on PyPI is a **direct git
reference** in `manifest.json`'s `requirements` array, using the syntax
HA's own developer docs specify:

    "<library>@git+https://github.com/<user>/<project>.git@<git ref>"

e.g., once/if the library fork is pushed somewhere Adam controls:

    "whirlpool_sixth_sense@git+https://github.com/<owner>/whirlpool-sixth-sense.git@compatibility/1.3.1-api144-laundry-controls"

HA's automatic dependency installer then runs `pip install` for that
requirement string during integration setup, the same way it does for any
PyPI package - Adam would not run any manual command at all. **This
requires the git ref to be reachable over the network from Adam's HAOS
Core container at setup time** - a purely local, unpushed branch (which is
all that exists right now) cannot be referenced this way. That is a
publication decision requiring Adam's explicit approval before it can be
used, exactly like publishing anything else in this project - see the
implementation report's HAOS section for the exact next-step framing.

This manifest currently pins `whirlpool-sixth-sense==1.3.1.post1` (an
**exact** pin, matching the stable-version discipline of this fork, not a
`>=` open range) for a specific, non-obvious reason: Adam's HAOS already
has the real, unpatched, PyPI-published `whirlpool-sixth-sense==1.3.1`
installed for the existing stock integration. Home Assistant's dependency
installer treats a requirement as "already satisfied" purely by comparing
version *strings*, not contents - if this fork's library also reported
itself as plain `"1.3.1"`, HA would see the stock 1.3.1 already installed,
consider `==1.3.1` satisfied, and never install this patched copy at all.
The paired library fork's `pyproject.toml` therefore sets its own version
to `1.3.1.post1` (a real PEP 440 post-release identifier, greater than
`1.3.1`), and this manifest pins exactly that version, so Home Assistant's
installer can actually tell the two apart and will install/upgrade to the
patched one.

**A real, version-specific risk found during this research, not
resolved here:** [home-assistant/core#171055](https://github.com/home-assistant/core/issues/171055),
open at the time of writing, describes custom-integration dependencies
being "installed" into `/config/deps` on HA Core 2026.4+ (which includes
2026.8.3) but that directory not being on `sys.path`, so the import still
fails afterward even though the install step reported success. This may
or may not affect Adam's exact HAOS build. **Before relying on the git-URL
approach above, check Home Assistant's own logs on a test install for an
ImportError for `whirlpool` immediately after a "Requirement already
satisfied" or install-success log line** - if this bug is present on
Adam's exact build, the documented workaround in that issue is a manual,
one-time `pip install` run from the HAOS host's own container tooling
(not something this fork can silently do on Adam's behalf, and not
something to be done without Adam's own awareness and approval, since it
means altering the running Core container's packages directly).

## Testing / static validation performed

- `python3.13 -m py_compile` on every file in `custom_components/whirlpool/`
  **except** `config_flow.py`, which requires Python 3.14 (PEP 758) that
  this sandbox does not have installed - see above for how that file was
  verified instead.
- `ruff check` - all checks passed for every file this fork touches.
- Manual JSON validation of `manifest.json`, `strings.json`,
  `translations/en.json`, `icons.json` - all parse.
- Confirmed byte-for-byte identity between this branch's
  `homeassistant/components/whirlpool` baseline commit content and the
  real `home-assistant/core` `2026.8.3` tag, for every file in that
  directory, before making any change.
- **Not performed** (same sandbox limitations as Phase 5F): loading this
  integration inside a real Home Assistant instance; HA's own
  `hassfest`/manifest-schema validator; HA's translation-completeness
  checker; the real pytest suite (see the paired library fork's
  CHANGES.md for why).

## What did NOT change from Phase 5F's design

The button/binary_sensor logic itself - the DDM-proven MachineState
gating tables, the Remote-Enable-must-be-True-and-checked-twice pattern,
the translated `HomeAssistantError` on a blocked press, the reliance on
the existing push event socket with no added polling - is unchanged. See
the Phase 5F branch's own CHANGES.md for the full description; none of
that reasoning was version-specific.
