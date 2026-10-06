# Upstream handoff: Whirlpool laundry controls

## Goal

This branch is a temporary staging branch for contributing the laundry-control work back to the existing Whirlpool projects. It is **not** intended to become a separately branded or permanently maintained Home Assistant integration.

The intended end state is:

1. protocol/API changes are accepted into the upstream `whirlpool-sixth-sense` library;
2. Home Assistant entity/action/UI changes are accepted into the existing Core `whirlpool` integration;
3. this staging fork can be retired.

## Upstream targets

### Library / protocol

Upstream project: `abmantis/whirlpool-sixth-sense`

The existing development fork with real upstream ancestry is:

`aevans0001/whirlpool-sixth-sense`

That fork contains the API144 washer/dryer work and its history. The separately published `aevans0001/whirlpool-legacy-library` repository is only a curated pinned distribution used for validation; it is **not** the repository that should be proposed as a permanent upstream replacement.

Library responsibilities include:

- washer/dryer Start, Pause, Resume, Cancel protocol operations;
- read-only Remote Control Enable state;
- WFW9620HBK3 cycle/options/dispenser support;
- WED9620HBK2 cycle/options support;
- cycle-specific temperature, spin, soil, rinse, presoak, steam, Fan Fresh and dryer configuration write support;
- capability/changeability helpers used by Home Assistant;
- protocol payload construction and cloud/API behavior.

The old compatibility branch was based on `whirlpool-sixth-sense` 1.3.1. Before an upstream library PR is opened, the relevant changes need to be forward-ported/rebased onto the current upstream library architecture/version.

### Home Assistant

Upstream project: `home-assistant/core`

Component: `homeassistant/components/whirlpool`

This staging branch retains the upstream integration identity: **Whirlpool Appliances**, domain `whirlpool`, and the upstream codeowners.

Home Assistant responsibilities in this branch include:

- washer/dryer command buttons and availability policy;
- washer and dryer configuration selects;
- model/capability-aware entity availability;
- washer Specialty/Download & Go presentation for the validated model;
- Home Assistant-local Favorite Cycle storage and Save/Delete actions;
- Favorite application that configures a cycle without starting the appliance;
- washer remaining-time display/countdown behavior;
- translations and entity metadata.

The manifest currently points at a pinned development library commit so this staging branch remains testable. A final Home Assistant Core PR should instead depend on the released upstream `whirlpool-sixth-sense` version containing the accepted library changes.

## Validated behavior

The completed integration was validated against a live washer and dryer installation:

- 2 appliances discovered;
- 47 Home Assistant entities total;
- washer: 29 entities;
- dryer: 18 entities;
- washer/dryer Apply configures without sending Start;
- Favorite Save stores the currently reported recipe locally and sends no appliance command;
- Favorites are separate per washer/dryer and deletions persist;
- Specialty cycles are model-gated;
- Colors + Cold Wash remains selectable;
- Steam availability follows the destination cycle;
- washer remaining time counts down locally, freezes while paused, reaches 0 at completion, and clears while idle;
- dryer options follow changeability/cycle support rather than a blanket Remote Control Enable requirement.

The standalone validation suite completed with:

`329 passed, 14 skipped`

Hassfest also passed for the publication build, with only the expected warning that a custom copy using domain `whirlpool` collides with the built-in Core integration.

## Files added by the later validated work

New Home Assistant-side modules:

- `favorites.py`
- `remaining_time.py`
- `specialty.py`
- `services.yaml`

The largest functional changes are in:

- `select.py`
- `sensor.py`
- `number.py`
- `config_flow.py`
- `strings.json`
- `translations/en.json`

The earlier command-button work remains in `button.py` and `binary_sensor.py`.

## Tests retained on this staging branch

The `tests/` directory contains the standalone validation suite used during development, including coverage for:

- baseline regular-cycle behavior;
- cycle labels;
- dryer configuration;
- dynamic Favorites;
- Favorite capture/apply/storage;
- remaining-time behavior;
- Specialty payloads and latch behavior.

These tests are evidence/supporting material. For a Home Assistant Core PR, the relevant cases should be adapted into Core's normal `tests/components/whirlpool/` structure and conventions.

## Publication repositories

`aevans0001/Whirlpool-Legacy` and `aevans0001/whirlpool-legacy-library` were created as temporary clean/public distribution artifacts during validation.

They should not be treated as long-term product identities or as replacements for the existing Whirlpool projects. No long-term "Whirlpool Legacy" brand is intended.

## Recommended upstream sequence

1. Forward-port the library changes from `aevans0001/whirlpool-sixth-sense` onto the current upstream library baseline.
2. Run the upstream library's own tests and open a focused PR to `abmantis/whirlpool-sixth-sense`.
3. After the library changes are accepted/released, update this staging integration to that released dependency.
4. Rebase/adapt the Home Assistant changes against current `home-assistant/core` `dev`.
5. Move/adapt the relevant tests into `tests/components/whirlpool/`.
6. Run Core Whirlpool tests, Ruff, mypy where applicable, and Hassfest.
7. Open the Home Assistant Core PR to the existing Whirlpool integration.
8. Once upstream adoption is complete, retire/archive the temporary distribution repositories.
