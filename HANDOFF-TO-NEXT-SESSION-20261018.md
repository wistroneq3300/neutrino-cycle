# HANDOFF TO NEXT SESSION — Vera cycle harness (ts1)

> Written: 2026-10-18 01:40 (+08)
> For: the NEXT conversation window (assume you know nothing about the prior chat)
> Repo (working): `/root/vera-cycle-ts1`, branch `ts1` @ `904cdb8` (== origin/ts1)
> Language policy: this doc is English, EXCEPT §6 續接點 which is deliberately 繁體中文.

---

## 0. TL;DR — what state you are inheriting

- The main deliverable of the previous session is **DONE and pushed**: the cycle
  report is 100% English, the bilingual validation spec ships beside it, and the
  Samba delivery for run `neutrino_power_cycle_outband_20261016_233643_136f68`
  is accepted.
- A code change was committed to `ts1` (SEL collection now always uses OOB) and
  pushed. **`main` was NOT touched.**
- The previous session also did housekeeping: cleaned `/srv/cycletmp` test
  debris, updated `AGENTS.md` and `.openhands/memory/*.md` for a directory
  rename, and cleaned a stale local clone.
- **There is no open work item.** §6 lists optional follow-ups only.

---

## 1. Two local clones of the SAME GitHub repo (do not confuse them)

Remote (both clones): `https://github.com/wistroneq3300/vera-cpu-rack-cycle.git`
(note: GitHub redirects this; a `warning: redirecting to ...` line on push is normal).

| Directory | Branch | HEAD | Role |
|---|---|---|---|
| `/root/vera-cycle-ts1` | `ts1` | `904cdb8` | **working dir for all recent work** |
| `/root/vera-cycle-eb1` | `main` | `eb047a6` | main-line clone (was `/root/vera-cycle`; renamed) |
| `/root/vera-cycle` | — | — | **no longer exists** (renamed to `-eb1`) |

Remote branches right now:
- `origin/main` = `498cb36`  (untouched by the last session)
- `origin/ts1`  = `904cdb8`  (pushed by the last session)

**Convention going forward: do your work in `/root/vera-cycle-ts1` on branch `ts1`.**
`ts1` is intentionally NOT merged to `main` (user decision).

---

## 2. What was completed (last session), with commits

`origin/ts1` log (newest first):
```
904cdb8 docs: point AGENTS.md at the renamed local clone /root/vera-cycle-eb1
85729da handoff: record b5e8f2a as pushed; refresh §5 續接點 and §7
b5e8f2a sel: collect SEL over OOB on all channels; refresh spec, config and tests
9822dfd report: keep campaign.json outside the bundle, drop cycle_summary.json   (pre-existing)
```

**`b5e8f2a` (13 files) — the substance:**
- `cycle_engine.py`: `sel_command` now collects **SEL list AND sel clear over OOB**
  for every channel (was: OS-side `ipmitool sel` when `channel=inband`). Reason:
  the OS-side path needs `/dev/ipmi0`, absent on this reworked platform.
  **inband `ipmitool power cycle` was intentionally LEFT UNCHANGED** (user: only
  inband can do it this way).
- `cycle_specification.py`: item 17 text now says "SEL is always collected over
  authenticated OOB", so the delivered bilingual spec matches the code.
- `cycle_report.py`: journal root is resolved **per call** from `VERA_CAMPAIGN_TMP`
  (default `/srv/cycletmp`) via new `campaign_tmp()` + `journal_path()`. This
  removed import-order fragility and made tests hermetic.
- `dev/tests/*` (6 files): read/write the out-of-bundle journal via `journal_path`,
  point `VERA_CAMPAIGN_TMP` at a temp dir, drop the obsolete `cycle_summary.json`
  assertions. **All 323 tests pass.**
- `neutrino_config.sh` (NIC 22→17, PCIEFAB_MIN 20→17), `naboo_config.sh`
  (`mst start` before MST table read), `cycle_inventory_neutrino.csv`
  (new lab addressing 10.36.66.x, hostnames `localhost-nX`).

**`904cdb8`:** `AGENTS.md` line 12 & 89 path updated to `/root/vera-cycle-eb1`.

**Housekeeping (NOT in git — `.openhands/` is untracked):**
- `.openhands/memory/{MEMORY.md, REDFISH_EVENTLOG_design.md, 2026-10-02.md,
  2026-10-06.md}`: `/root/vera-cycle` → `/root/vera-cycle-eb1` (5 refs).
  Backups: same name + `.bak_20261018_repath`.
  (Other mentions like `/root/sheng/vera-cycle/`, `/root/samba/vera-cycle/` are
  DIFFERENT paths and were correctly left alone.)
- `/srv/cycletmp`: deleted test debris (all `neutrino_power_cycle_inband_*`,
  `tmp*`, and `output/`). It is now **empty**. No real run data lived there.
- A third clone `/root/vera-cpu-rack-cycle` was DELETED by the user.

---

## 3. The deliverable itself (report size / Samba)

Full detail lives in `HANDOFF-REPORT-SIZE-20261017.md` (tracked, English + §5 中文).
Summary:
- Main report: `/root/samba/neutrino_power_cycle_outband_20261016_233643_136f68/CYCLE_REVIEW_REPORT.html`
  — **0 CJK** (pure English).
- `CYCLE_VALIDATION_SPECIFICATION.html` — the **only** intentionally-bilingual file.
- Delivery is complete: all in-report links resolve, node evidence dirs present,
  no `campaign.json` / `cycle_summary.json` inside the delivery.
- **Rule unchanged:** never modify other pre-existing data in `/root/samba`
  (CIFS mount `//10.33.34.22/eq3300/samba_tmp`).
- **Decision A:** campaign journal lives at `/srv/cycletmp/<run_id>/campaign.json`
  (now overridable via `VERA_CAMPAIGN_TMP`).

---

## 4. Key facts / gotchas to save you time

- **Run tests with:** `cd /root/vera-cycle-ts1 && PYTHONPATH=.:dev/tests python3 -m unittest discover -s dev/tests -p 'test_*.py'`
  → expect `Ran 323 tests ... OK`.
  Individual file: `PYTHONPATH=. python3 dev/tests/test_cycle.py` (files import
  `cycle_core` etc. from repo root, so PYTHONPATH matters).
- **Push works** via the environment's git credential helper (no inline token
  needed). `git push origin ts1` works from `ts1`.
- `AGENTS.md` is **Non-ISO extended-ASCII** (not valid UTF-8) — the file editor
  cannot read it; use `sed`/`grep` for edits.
- The run generator writes ONLY `CYCLE_REVIEW_REPORT.html` (see `_write_reports`
  in `cycle_report.py`). `CYCLE_REVIEW_MERGED.html` is an obsolete snapshot.
- `cycle_report.py` no longer emits `cycle_summary.json` (dropped in `9822dfd`).
- Only two things in the whole codebase use OS-side (inband) ipmitool:
  1. SEL — **now moved to OOB**; 2. `ipmitool power cycle` when `channel=inband`
  — left as-is by design.

---

## 5. Explicit non-goals / do-not-do

- Do NOT merge `ts1` into `main` (user said no).
- Do NOT commit `*.bak_*`, `*.orig.bak`, `*.md.bak_*`, `docs/SOP_cycle_zh-TW.html`
  (user said not to).
- Do NOT modify anything else in `/root/samba`.
- Do NOT put `campaign.json` / `cycle_summary.json` into the delivery dir.

---

## 6. 續接點（給下一個對話視窗）

> 目前**沒有進行中的工作**，上一輪全部收尾完成且已 push。以下皆為「可選」，沒被要求就別動。

1. **環境確認（建議先做）**
   - `cd /root/vera-cycle-ts1 && git fetch origin ts1 && git status` → 應在 `ts1` @ `904cdb8`、工作區只有 untracked 的 `*.bak_*` / `docs/SOP_cycle_zh-TW.html`。
   - 跑一次測試確認綠燈：`PYTHONPATH=.:dev/tests python3 -m unittest discover -s dev/tests -p 'test_*.py'`（應 323 pass）。

2. **可選 — 之後再跑新 run 時驗證瘦身**
   - 新 run 的 journal 應直接落 `/srv/cycletmp/<run_id>/campaign.json`、bundle 內不再產生 400+ MB 檔。
   - （本輪已把測試改為 hermetic；`/srv/cycletmp` 目前是空的。）

3. **可選 — inband power cycle**
   - `cycle_engine.py` 的 `ipmitool power cycle`（`channel=inband`）依使用者指示**保留不動**。若未來要處理，需先確認 reworked platform 是否真的無 `/dev/ipmi0`。

4. **可選 — 交付加分**
   - 可在 Samba 交付目錄放 `MANIFEST.md` / checksums 讓接收方自驗（非需求；加之前先與接收方確認）。

5. **不要做**（重述）
   - ❌ 不合併 `ts1` → `main`；❌ 不清 `main`；❌ 不動 `/root/samba` 其他資料；❌ 不把 journal/`cycle_summary.json` 放進交付目錄。

---

## 7. Quick file map

- Working repo: `/root/vera-cycle-ts1` (branch `ts1`)
- Main-line clone: `/root/vera-cycle-eb1` (branch `main`)
- Report-size condominium: `HANDOFF-REPORT-SIZE-20261017.md` (tracked)
- SEL change: `cycle_engine.py::sel_command` (always role `'oob'`)
- Journal root: `cycle_report.py::campaign_tmp()` / `journal_path()` (`VERA_CAMPAIGN_TMP`)
- Samba mount: `//10.33.34.22/eq3300/samba_tmp → /root/samba` (CIFS, user eq3300)
- This run's source bundle: `campaigns/neutrino_power_cycle_outband_20261016_233643_136f68/`
