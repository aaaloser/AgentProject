# Evaluation Case Design Checklist

- [ ] Bug behavior is deterministic for fixed input.
- [ ] Upstream-owned tests pass in both bug and fixed states.
- [ ] Default public pytest and the standalone repro fail in the bug state and pass in the fixed state.
- [ ] Hidden behavior tests fail in the bug state and pass in the fixed state.
- [ ] Hidden tests assert observable behavior, not unknowable exact messages or implementation paths.
- [ ] Task text states the symptom and public repro command without naming the source file or fix.
- [ ] Controller-only localization is at most 10 steps and the reference fix is at most 40 changed lines.
- [ ] Runtime imports resolve to the mounted workspace source.
- [ ] A temporary broken production edit turns both public paths red and restoration turns them green.
- [ ] The default pytest path exposes the same public behavior as the standalone repro.
- [ ] Tests, repro, license/provenance, absent test hooks, symlinks, and runtime-cache exceptions are covered by protected-manifest checks.
- [ ] Source commit, archive hash, license, dependency lock, base image digest, build command, and final image ID are recorded.
