# Documentation assets

- `architecture-light.svg` and `architecture-dark.svg` are generated from
  `build-architecture-svg.py`.
- Run `python3 docs/assets/build-architecture-svg.py` after changing the diagram.
- Run `python3 docs/assets/build-architecture-svg.py --check` before committing;
  docs CI runs the same check.
- `logos/` contains the local brand icons embedded into the generated SVGs as
  data URIs. The output has no remote CDN or icon dependency. Keep only icons
  used by the generator.
- Do not hand-edit the generated SVGs.
