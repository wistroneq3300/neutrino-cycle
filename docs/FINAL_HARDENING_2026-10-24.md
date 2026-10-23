# Vera CPU Rack Cycle final hardening acceptance record

- Date: 2026-10-24 (UTC+8)
- Release: `2026.10.24.2`
- Source branch: `codex/ts1-p0-p1-hardening`
- Verified source HEAD: `2a201fda13c950a980887c5631dc89f436354241`
- Delivery branch: `codex/vera-cycle-final-hardening-v1`

The remote source branch was fetched before development. Its HEAD exactly matched the requested source commit, so there was no newer source delta to reconcile. The delivery branch was created from that commit. This record is for offline implementation verification; it is not a claim of live-rack acceptance.

## Independent-review correction pass

An independent review of delivery commit `99d79174da9edc13933ebbd4d49fac6f4c29e355`
identified three P1 correctness defects and two P2 trace/display defects. Release
`2026.10.24.2` applies narrow corrections on the same delivery branch:

- dmesg delta allocation now compares exact timestamp-free entries while keeping
  counter-free device/message identities only for logical grouping. Count
  conservation holds when different I/O/QID values alias and when an overlapping
  capture changes from A to A+B.
- Redfish raw Event IDs remain attached to each logical per-loop observation;
  lifecycle and cards use service plus non-empty message, are chronologically
  ordered, and take the worst same-loop severity before segmentation.
- PCI, network, USB/BMC USB and sensor recovery require that collector's own
  successful, usable observation metadata. An unrelated hardware script cannot
  prove recovery.
- Named hostname checks retain an ordered compact trace without adding duplicate
  failure cards or changing keep-going/power behavior.
- A report outcome updates the text and Markdown current-state lines after the
  single HTML attempt. Manual rebuild READY and FAILED history are both retained.
  A lightweight-summary write failure rolls back the pair, records
  `summary_state=FAILED`, and does not overwrite READY HTML state or rerender it.

## Approved decision status (13 ED + 8 FIX = 21)

| Decision | Status | Implementation and verification |
|---|---|---|
| ED-CYCLE-01 | Implemented | PRE blank/mismatch blocks before mutation; START mismatch refuses start; loop blank/mismatch is FAIL, remains active, and cannot be washed out by a later good identity check. |
| ED-CYCLE-02 | Implemented | Normal loop has one final `dmesg -c`, after POST/MCTP work. No normal pre-reboot collection was added; abnormal recovery-tail collection remains. |
| ED-CYCLE-03 | Implemented | Journal/JSON failure records FAILED/DEGRADED without stopping the cycle; HTML failure is independent of execution/health and retains reason/history. No power retry is triggered. |
| ED-CYCLE-04 | Implemented | dmesg uses device-qualified observation identities and multiset deltas, preserving same-device repeats, distinct BDFs, raw evidence, and non-duplicated overlap counts. |
| ED-CYCLE-05 | Implemented | Empty successful services PASS; absent SEL service is PASS/N/A; warnings WARN, criticals FAIL, incomplete/timeout UNAVAILABLE. EventLog and SEL identities remain service-qualified; severity changes stay in one card as separate segments. |
| ED-CYCLE-06 | Implemented | HTML state transitions FAILED→READY after manual rebuild while retaining timestamped failure history. Report state is independent of campaign execution and health. |
| ED-CYCLE-07 | Implemented | Lifecycle is NEW→KNOWN; only confirmed available absence marks recovery; reappearance is RECURRENCE. Cards are keyed by node/device-or-service/error and segmented on gap, lifecycle, or severity. |
| ED-CYCLE-08 | Implemented | Checkpoints persist structured state/evidence each loop; full HTML is generated only at a terminal, safely handled state. |
| ED-CYCLE-09 | Implemented | Delivery ZIP contains HTML, JSON, logs, evidence, inventory/config snapshots; excludes the external campaign journal and private SSH material; source journal is untouched. |
| ED-CYCLE-10 | Implemented | Startup discovers locally interrupted RUNNING campaigns and offers rebuild/view/skip. Skip is non-mutating; rebuild uses retained records; no automatic cycle/resume/backfill occurs. |
| ED-CYCLE-11 | Preserved | Repository-root startup contract remains; arbitrary-CWD support was not added. |
| ED-CYCLE-12 | Preserved/verified | Fatal recovery/execution loss deactivates only that node; other nodes continue. PCIe, sensor, dmesg, and hostname health failures do not stop operable nodes. |
| ED-CYCLE-13 | Implemented | Terminal HTML policy is shared with ED-CYCLE-08; SIGKILL leaves checkpoints for explicit offline rebuild. |
| FIX-01 | Implemented | Normal dmesg collection timing and one-read rule locked by regression. |
| FIX-02 | Implemented | Strict hostname behavior and immutable loop FAIL locked by regression and documentation. |
| FIX-03 | Implemented | Exact dmesg device/occurrence/overlap accounting locked by parser and engine regression. |
| FIX-04 | Implemented | Redfish empty/unavailable/service isolation/severity transition semantics locked by regression. |
| FIX-05 | Implemented | NEW/KNOWN/RECURRENCE state machine and compact HTML card/segment model locked by regression. |
| FIX-06 | Implemented | READY/FAILED/manual-rebuild history and report/execution separation locked by regression. |
| FIX-07 | Implemented | Interrupted-campaign discovery, skip, manual rebuild, and no-power behavior locked by regression. |
| FIX-08 | Implemented | `AGENTS.md`, README, implementation/validation specs, generated HTML, tests, and superseded review/action items were synchronized; obsolete hostname WARN guidance was removed. |

## Requested regression acceptance (21 items)

| # | Acceptance | Result | Evidence |
|---:|---|---|---|
| 1 | PRE hostname mismatch/blank BLOCKED | PASS | `test_wrong_hostname_blocks_pre_before_any_change`, `test_empty_hostname_blocks_pre` |
| 2 | Loop hostname mismatch FAIL and continue | PASS | `test_loop_hostname_mismatch_is_fail_and_node_continues`, existing blank/POST hostname cases |
| 3 | Same-round recovery cannot erase FAIL | PASS | `test_transient_loop_mismatch_cannot_be_washed_out_later_in_round`, ordered trace regression |
| 4 | Same-device dmesg repeats counted | PASS | `test_same_device_repeat_keeps_its_count`, alias count-conservation regression |
| 5 | Distinct BDFs retained | PASS | `test_second_bdf_is_a_distinct_observation`, `test_different_devices_same_error_are_not_swallowed` |
| 6 | Overlapping capture not double-counted | PASS | overlap regression plus A→A+B changing-signature regression |
| 7 | Empty Redfish log PASS | PASS | Redfish empty-service/delta suite |
| 8 | Redfish timeout UNAVAILABLE | PASS | `test_logservices_timeout_is_unavailable_not_absent` and Redfish failure suite |
| 9 | EventLog/SEL IDs isolated | PASS | service-qualified identity, pipe-containing message and raw-ID retention regressions |
| 10 | WARN→Critical becomes FAIL | PASS | severity transition plus same-loop multi-ID worst-severity regressions |
| 11 | NEW/KNOWN/RECURRENCE | PASS | confirmed recovery and new-Event-ID recurrence regressions |
| 12 | UNAVAILABLE is not recovery | PASS | Redfish gap plus formal PCI/network/USB/BMC-USB/sensor collector metadata regressions |
| 13 | No full HTML rebuild per loop | PASS | `test_full_html_is_rendered_once_at_terminal_state_not_each_loop` |
| 14 | Terminal HTML generated | PASS | same terminal-render test plus report suite |
| 15 | Manual rebuild changes HTML state to READY | PASS | rebuild plus Journal/run-status/text/Markdown state-consistency regression |
| 16 | FAILED history retained | PASS | same failure-history regression and degraded-output suite |
| 17 | SIGKILL/offline rebuild | SKIP | dead-owner, partial-record and manual offline rebuild tests pass, but this Windows host cannot perform the required end-to-end POSIX runner SIGKILL scenario; OpenHands/Linux handoff required |
| 18 | One failed node stops; other nodes continue | PASS | `test_two_nodes_only_execution_failure_stops` |
| 19 | ZIP excludes journal | PASS | `test_delivery_zip_includes_evidence_and_snapshots_but_never_journal` |
| 20 | 4 nodes × 280 loops report opens | PASS | current anomaly-rich synthetic test covers changing hostname traces, aliased dmesg entries, unique Redfish IDs and WARN/FAIL segments; installed Chrome headless parsed a separately generated temporary current 2,544,930-byte report and found Loop 280, final trace, capped IDs and 12 logical cards |
| 21 | JSON/log/evidence retained | PASS | ZIP byte-for-byte evidence assertion, checkpoint/rebuild suites, and report evidence-link tests |

## Verification result

- Full discovery: 438 total; **416 PASS, 0 FAIL, 0 ERROR, 22 SKIP**.
- Explicit skips: 18 hardware-script cases and 2 Run 2 shell-parser cases require Bash; 1 lock-permissions case requires Linux root/cross-UID; 1 wizard case requires POSIX PTY.
- Requested acceptance matrix: **20 PASS, 0 FAIL, 1 SKIP**. Item 17's
  end-to-end runner SIGKILL gap is explicit and is not counted as PASS; it is
  separate from the test runner's 22 environment-specific skips.
- Final-hardening focused suite: 29/29 PASS.
- Scale coverage: the checked regression renders 1,120 anomaly-bearing synthetic
  loop records (five identity checks per loop, aliased dmesg entries, unique raw
  Redfish IDs and repeated severity transitions), retains the last-loop values,
  produces 12 logical issue cards and enforces a 12 MiB upper bound. The existing
  older pass-oriented `test-results/final-4x280` fixture remains a separate,
  clearly marked `SYNTHETIC DEMONSTRATION` and is excluded from Git.
- Browser check: installed Chrome headless parsed a separately generated
  temporary current anomaly-rich 2,544,930-byte report into a complete
  2,455,442-character DOM; Loop 280, `wrong-4-280-4`, `(20 distinct IDs)`,
  `Issues (12)` and the closing HTML node were present. This did not overwrite
  the older `test-results/final-4x280` fixture.
- Historical source data: no historical campaign directory or evidence file was modified or deleted. Existing checked-in fixtures were consumed read-only; scale validation used an explicitly synthetic fixture.
- Hardware safety: no real power-cycle command, rack SSH, BMC/OS write, package installation, or physical-device operation was executed.

## Remaining limits and risk

- No unresolved P0 issue is known from offline verification.
- P1 acceptance remains for a controlled Linux/rack run: the 22 environment-specific skips, an end-to-end running-runner SIGKILL/offline rebuild, actual BMC power command/recovery timing, real Redfish vendor variants, real `dmesg -c` behavior, and Linux cross-user journal/lock permissions.
- The report scale check proves generation and browser parsing/opening, not interactive performance on every operator workstation.
- Live credential/endpoint behavior was deliberately not exercised. No password, token, or SSH private key is added by this change. The requested source commit already contained plaintext-looking credential examples in historical `AGENTS.md`; the final tree removes them, but parent/source Git history remains public under the no-rewrite/no-force-push constraint. Treat those values as compromised and rotate them immediately if they are real.

## Self-review safety invariants

- Power-action dispatch branches and action counts are unchanged; no hostname, log, persistence, HTML, or recovery failure resends power.
- Normal-loop OS dmesg is read once at the end; the pre-action/early-POST read was not reintroduced and the abnormal recovery tail remains.
- FAIL/WARN and true occurrence counts survive aggregation; different nodes, BDFs, Redfish services, and errors cannot cross-merge.
- RECURRENCE requires a confirmed available absence; UNAVAILABLE never marks recovery.
- READY HTML cannot overwrite execution/health, and persistence failure is visible in run status plus any successfully rendered terminal HTML.
- A failed node is removed from subsequent actions without stopping still-operable nodes.
- Checkpoints retain completed loop JSON/evidence before terminal HTML; SIGKILL recovery never fabricates or replays a loop.
- No tracked historical campaign/test-result file changed; the generated scale fixture remains ignored and synthetic.
- Current-tree secret-pattern and added-assignment scans are zero. The inherited-history credential warning above remains a separate operational risk.

## Independent review handoff (OpenHands)

Review these high-risk paths first:

1. `vera_cycle/engine/cycle_engine.py`: `identity`, `capture`, `collect_dmesg`, and recovery-tail behavior. Confirm trace completeness, exact-entry delta allocation, exactly one normal final `dmesg -c`, and no added power action.
2. `vera_cycle/core/cycle_dmesg.py` and `cycle_core.py`: `_strip_count`, `_bundle_event`, `_split_dmesg_bundle`, `_lifecycle_issue_key`, `_observation_state`, and `aggregate_issues`. Verify count conservation, Redfish raw/logical identity, source-specific UNAVAILABLE, and no node/device/service cross-merge.
3. `vera_cycle/reporting/cycle_report.py`: `_redfish_event_key`, `merge_issues`, `_issue_segments`, `_write_reports`, `_write_current_summaries`, `_render_reports`, `rebuild`, and `create_delivery_zip`. Check chronological segmentation, summary rollback, READY/FAILED history, single HTML render, and journal exclusion.
4. `vera_cycle/cli.py`: terminal checkpoint/report flow and interrupted-campaign prompt. Confirm skip is non-mutating and rebuild never invokes cycle/action paths.
5. `dev/tests/test_final_hardening.py`, `test_dmesg_bundle.py`, `test_redfish_failures.py`, and `test_run2_recovery.py`: audit failure-first coverage and ensure mocks do not conceal a production call-order regression.

Also compare the final diff against the source commit to confirm power dispatch count, normal dmesg timing, per-node independence, historical campaign immutability, and absence of credentials.
