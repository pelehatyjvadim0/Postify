# SDD ledger — plan: docs/superpowers/plans/2026-08-08-wave-3-content-packages.md

Task 1: complete (commit fde7c53, spec/plan and S_n baseline fixed)
Task 2: complete (commit 4d86513, initial RED 83+9, retained 160+26 GREEN)
Task 3: complete (commits e199094..eeaaa0b, initial implementation GREEN 243+35)
Task 4: broad fix dispatch BLOCKED without changes (54 RED decomposed before round count)
Task 4A: fix round 1/5, RED ready (commit 123a99d; 24 adapter RED plus
1 Task 4B bootstrap-wiring RED; next: Terra implementation from the saved brief)
Task 4A: fix round 1/5 (5 original findings addressed, 3 open — symlink
TOCTOU, proxy/UDS bypass, multi-address fallback; commit 14621ce)
Task 4A: fix round 2/5, RED ready (commit 9b99285; 4 RED, 59 retained GREEN)
Task 4A: fix round 2/5 (2 addressed, 1 open — ConnectTimeout must fall back;
commit 84a5420)
Task 4A: fix round 3/5, RED ready (commit 9cd24fc; 1 RED, 63 retained GREEN)
Task 4A: fix round 3/5 (1 addressed, 0 open; commit 8a5b39b)
Task 4A: complete (commits 7424d4a..8a5b39b, scoped review clean)
Task 4B: in progress (12 RED: Codex isolation/schema, ports and bootstrap)
Task 4B: fix round 1/5 (review: repository/work same-path isolation,
selected/nonselected runtime batch, cleanup failure, media/work separation,
typed PackageDraft; commit a1343e1)
Task 4B: fix round 1/5, RED ready (commit fe128f8; 8 RED, 14 retained GREEN)
Task 4B: fix round 1/5 (2 addressed, 4 open — same-path outside-root,
selector schema relation, bidirectional root overlap, bool runtime validation;
commit 85800f2)
Task 4B: fix round 2/5, RED ready (commit 3da3912; 10 RED, 40 retained GREEN)
Task 4B: fix round 2/5 (4 addressed, 0 open; commit db7b0f1)
Task 4B: complete (commits 8a5b39b..db7b0f1, scoped review clean; 1 minor deferred)
Task 4B: minor (deferred): use explicit None checks for injected transport/policy
Task 4C: in progress (retry credits and atomic terminal package)
Task 4C: fix round 1/5 (review: complete_package must reject non-terminal target;
commit fe541ec)
Task 4C: fix round 1/5, RED ready (commit ae27464; 1 RED, 41 retained GREEN)
Task 4C: fix round 1/5 (1 addressed, 0 open; commit caf37fd)
Task 4C: complete (commits db7b0f1..caf37fd, scoped review clean; 1 minor deferred)
Task 4C: minor (deferred): concurrent complete/fail stress test
Final review: pending (deferred minors: falsy injection, concurrent terminal
stress, get_package snapshot consistency from initial review)
Final review: 12/12 mutations RED, full gates GREEN; 1 Important open —
run-once CLI leaks RuntimeError/traceback; final fix wave 1/1 pending Sol RED
Final fix wave: complete (RED ab05150, GREEN 63abe0b, scoped re-review clean)
Final review: complete (12/12 mutations RED; 0 Critical/Important; 3 minors deferred)
Live proof: article HTTP и Wikimedia GREEN; Commons returned URL проходит
strict MIME whitelist (`image/jpeg`, `image/png`, `image/webp`).
Live fix Wikimedia: complete (RED `418ec2a`, GREEN `ab3df25`, fresh scoped
re-review Approved без Critical/Important/Minor; MIME Important закрыт).
Official operator Codex preflight всё ещё ждёт явного подтверждения.
