# Click 8.4.2 snapshot provenance

This directory is an allowlisted source snapshot used for deterministic, offline evaluation. Click is not installed into the evaluation image; `PYTHONPATH=/workspace/src` resolves this source tree directly.

```json
{
  "adaptations": [],
  "base_image": "python:3.13-slim@sha256:8d9d0b8bcf6506481eae4907c18f5e3e7902e629f5f6d684f9e7c32e85e3ddf0",
  "build_command": "docker build --pull -t mokioclaw-eval-click:8.4.2 evals/images/click",
  "build_time_utc": "2026-09-22T11:06:46.165379302Z",
  "commit": "b2e30a175449cfda909ee4fbf4a29a6a071cad53",
  "dockerfile_sha256": "D292B6F30B15DA6CDD35F22F80AB30D329EF48E2BBB7440D338FF7216C9AD248",
  "github_archive_sha256": "D8D8D38A9AA4ED9216C78A3A153F772A380466302A1332F39C60396CA8FA6878",
  "image_id": "sha256:47142d38ecbb3be8ec5ad6c549f743b0b51ba413afa0bd82476b4249341a0d94",
  "image_tag": "mokioclaw-eval-click:8.4.2",
  "license": "BSD-3-Clause",
  "license_sha256": "9A8AD106A394E853BFE21F42F4E72D592819A22805D991B5F3275029292B658D",
  "metadata_only_fallback": false,
  "pruned": [
    ".devcontainer",
    ".github",
    ".pre-commit-config.yaml",
    ".readthedocs.yaml",
    "docs",
    "examples",
    "README.md",
    "uv.lock"
  ],
  "pypi_sdist_sha256": "9A6CEA6E60B17EBE0A44C5CC636D94F09BD66142C1CD7D8B4CD731C4917A15F6",
  "release": "8.4.2",
  "requirements_in_sha256": "F40723C374D8534AB2A6295025F6D643F81EEAC4D826DB1E48947662A073A520",
  "requirements_lock_sha256": "62AB584CF26216FCFF3ABA05176A8E6E8C4BA9AD38E8B806D75AABBAF2A5B47F",
  "retained": [
    "CHANGES.md",
    "LICENSE.txt",
    "pyproject.toml",
    "src/click",
    "tests"
  ],
  "source": "pallets/click",
  "system_dependencies": {
    "less": "668-1"
  },
  "tag_object": "c6b2d71ee056a96b8e6e06e6c29f67c1a766f8e4",
  "vendor_tree_sha256": "28C080E63CD9BA5CB050589C0C892031343A84F533C92A1FFBAA1356D6B9ADFB"
}
```

The approved plan referred to `CHANGES.rst`; the fixed upstream commit contains `CHANGES.md`. The real upstream filename is retained without modification. The GitHub archive is the vendoring source; the PyPI sdist and matching license hash are independent cross-checks.
