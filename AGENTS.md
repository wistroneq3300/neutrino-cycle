# AGENTS.md — vera-cpu-rack-cycle

Agent-facing implementation contract. Run from the repository root; arbitrary
working directories are intentionally unsupported. Never execute a real power
action during development verification, mutate historical campaigns, or commit
passwords, tokens, private keys, generated campaigns, or runtime Journals.

## Entry points and layout

- `neutrino_cycle.py` calls `vera_cycle.cli.main`.
- `vera_cycle/paths.py` is the sole source of repository-relative paths.
- `vera_cycle/core/` owns pure parsing, comparison, storage, transport and dmesg.
- `vera_cycle/engine/` owns node execution, runtime locks and recovery.
- `vera_cycle/reporting/` owns the terminal report and validation specification.
- `projects/<project>/` owns inventory and project-specific hardware checks.
- `dev/tests/` is offline; fake transports must never contact rack equipment.
- `campaigns/` is ignored, historical evidence, and read-only to development.

Run the offline suite with:

```bash
python3 -m unittest discover -s dev/tests -p 'test_*.py' -v
```

Linux/Bash/PTY-only tests must report an explicit SKIP when their environment is
unavailable. A SKIP is never counted as PASS.

## Final approved behavior

- Hostname is an identity gate. Missing/mismatched PRE identity blocks that node;
  START mismatch prohibits start. During a loop, a blank or mismatched hostname
  is `HOSTNAME_MISMATCH` FAIL for that loop while the operable node continues.
  Any mismatch in a loop remains FAIL even if a later check is healthy. Never
  retry a power action because of hostname failure.
- Nodes are independent. Only unrecoverable SSH/boot recovery stops that node;
  PCIe, sensor, dmesg, hostname and Redfish health findings do not stop other
  operable nodes or resend a power action.
- Normal loops collect OS dmesg once, at the end, with `dmesg -c`. Do not add a
  before-reboot or early-POST read. Keep the existing abnormal recovery-tail
  collection. A dmesg collection failure does not stop an operable node.
- dmesg occurrence counts are real observation counts. Repeated identical events
  count repeatedly, different BDFs remain separate, overlapping captures subtract
  their multiset overlap, and raw evidence is retained without rewriting counts.
- Redfish EventLog and SEL are separate services and event IDs never cross-match.
  A successful empty service is PASS; confirmed service absence is PASS / N/A;
  Warning is WARN; Critical is FAIL; timeout, invalid or incomplete data is
  UNAVAILABLE and never PASS. Severity changes create report segments and do not
  stop an otherwise operable node.
- Issue lifecycle is stateful per node/device/fingerprint: first observation NEW,
  continuous observation KNOWN, and reappearance after a confirmed healthy
  observation RECURRENCE. UNAVAILABLE is not proof of recovery. Report cards merge
  only the same node/device/error, use consecutive loop ranges, and split lifecycle
  or WARN/FAIL transitions. JSON, logs and evidence remain unchanged.
- During execution, checkpoint Journal/JSON/status and per-loop evidence only.
  Generate full HTML once at normal completion, graceful stop, or another safe
  terminal unwind. SIGKILL/power loss requires an operator rebuild.
- Execution, Health, Persistence and HTML Report are independent states. Journal
  or JSON write failure records FAILED/DEGRADED but does not stop cycling. HTML
  failure is FAILED, never changes execution/health, is not auto-retried, and
  preserves timestamped failure history; a successful manual rebuild becomes READY.
- Startup detects local dead-owner RUNNING campaigns and offers rebuild, view or
  skip. Skip deletes nothing and does not block a new campaign. Recovery never
  resumes/replays a loop, sends power, or treats an unfinished loop as PASS.
- Delivery ZIP contains HTML, JSON, console/log/evidence, inventory snapshot and
  config snapshot. It excludes the external/legacy Journal, writer locks and SSH
  state. The controller Journal remains in place; a ZIP need not rebuild elsewhere.
- Fix mature behavior only where a regression proves it incomplete. Do not merge,
  force-push, rewrite source branches, or change power-cycle counts.

## Security and operational boundaries

Credentials are supplied interactively or through documented environment variables;
only variable names may appear in the repository. Redfish tokens and passwords must
not enter argv, evidence, reports or Git. SSH host keys are pinned per run. Endpoint
locks are controller-local and never fail open. Project expected quantities remain
in the selected project config and must not be guessed.

Real rack acceptance is separate from offline verification. It requires an explicit
controlled run by an engineer with correct inventory, platform paths and credentials.
