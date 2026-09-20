# Rich v14.3.4 snapshot provenance

- Upstream URL: https://github.com/Textualize/rich.git
- Tag: `v14.3.4`
- Resolved commit: `ee8378c3bbbd7c75abc2f55c6c19e83b218ae81d`
- License: MIT (upstream `LICENSE` SHA-256 `deed7c17a4318158190a3ea239cc879a5a50271cebb98ae7025f48fbe58dca15`)
- Source archive URL: `https://codeload.github.com/Textualize/rich/zip/ee8378c3bbbd7c75abc2f55c6c19e83b218ae81d`
- Source archive SHA-256: `3390285ef57f8a4ee777e0bbe5e92e85d2b904b4d8a5524c1ab22dc1c9c56e1e`
- Vendor date: `2026-09-20`

## Vendor boundary

The snapshot was copied from the verified archive with this allowlist:

- `rich/`
- `tests/`
- `pyproject.toml`
- `poetry.lock`
- `LICENSE`
- `README.md`
- `CHANGELOG.md`

The upstream `.git/`, `.github/`, `docs/`, `assets/`, `benchmarks/`, `examples/`, `imgs/`, `questions/`, `tools/`, and all other top-level files were excluded. No generated build output is present in the vendor tree.

## Image and dependency lock

- Base image: `python:3.13-slim@sha256:8d9d0b8bcf6506481eae4907c18f5e3e7902e629f5f6d684f9e7c32e85e3ddf0`
- `requirements.in`: attrs 25.4.0, markdown-it-py 3.0.0, pygments 2.19.2, pytest 9.0.3
- `requirements.lock` SHA-256: `7b91fb686b51b937cee8599573d7144a0082bbe43b6045842fed8b52234c9ac4`
- `Dockerfile` SHA-256: `4b35152cedbcf25223730bd9107e07c98c8dd50fc09eb233335d82a7edb5cb13`
- Build command: `docker build --pull=false -t mokioclaw-eval-rich:14.3.4 evals/images/rich`
- Final image ID: `sha256:3e3b35aae4cf2420edc787f8a25d991d8a94a702cb972f31f339255cc661a7bb`
- The Dockerfile installs only the hash-locked requirements with `--require-hashes`; it does not install Rich from the network or as an editable package.
- The image uses the existing evaluator contract `ENTRYPOINT ["/bin/sh", "-lc"]` so command strings remain auditable and execute identically to the Python evaluation image.
- The image sets `PYTHONPATH=/workspace`. Under the acceptance mount, `rich.__file__` resolved to `/workspace/rich/__init__.py`, proving the workspace snapshot is the unique import source.

## Verification decision

- The preferred `pytest==9.0.3` lock was retained; no compatibility fallback was needed.
- Offline constrained upstream suite: `952 passed, 25 skipped in 11.32s`.
- Import acceptance passed under `--network none`, 1 CPU, 512 MB memory, read-only root, and a 64 MB `/tmp` tmpfs.

## Snapshot Case ledger

- `rich-markdown-hyperlinks-option-01`: the controller path is task → `repro_markdown_hyperlinks.py` → `Markdown.__init__` → `self.hyperlinks`; the mutation is one behavior line and the reference patch is one inverse line. The public bridge and repro share `render_disabled_link()`.
- The upstream `tests/test_markdown_no_hyperlinks.py` is the exact golden-output contract being challenged by this synthetic mutation, so the mutation-only controller smoke excludes that one target while keeping the remaining 951 upstream tests green. The formal Case public command remains `python -m pytest -q` and therefore records the red signal; the reference patch passes the full public command and hidden tests.
- `rich-table-no-edge-measure-02`: the controller path is task → `repro_table_no_edge_measure.py` → `Table._extra_width`; the mutation and reference are one inverse condition line. The mutation-only unrelated-suite smoke excludes the two upstream golden render tests (`tests/test_card.py`, `tests/test_table.py`) that directly encode the changed width contract; the remaining vendor tests stay green. The full Case public command and the three hidden measurement groups pass with the reference patch.
