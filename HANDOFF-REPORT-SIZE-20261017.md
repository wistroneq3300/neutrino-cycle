# HANDOFF — Report size / generation & Samba delivery

> Last updated: 2026-10-17 23:35 (+08)
> Branch: `ts1` @ `9822dfd` (== origin/ts1, verified)
> Run: `neutrino_power_cycle_outband_20261016_233643_136f68`
> This file supersedes the 20261017 23:25 version (kept as
> `HANDOFF-REPORT-SIZE-20261017.md.bak_20261017_2325`), which in turn superseded
> the 22:05 version (`HANDOFF-REPORT-SIZE-20261017.md.bak_20261017_220516`).
>
> Language policy: Sections 1–4 and 6–7 are English. Section 5 (續接點 / Next
> steps) is deliberately 繁體中文 per the handoff requirement.

---

## 1. Task

Deliver the cycle-log artifacts of this run cleanly over Samba, with these rules:
- The main report HTML must be **100% English** (no CJK). The **single exception**
  is `CYCLE_VALIDATION_SPECIFICATION.html`, which stays **bilingual**.
- The Samba delivery must be **complete/usable**: it must include the
  validation-spec HTML, all evidence files, and every in-report link must
  resolve (be clickable) from within the delivery directory.
- **Do not touch any OTHER pre-existing Samba data**; manage only this run's
  delivery directory.
- **Decision A (chosen):** hardcode the campaign journal to
  `/srv/cycletmp/<run_id>/campaign.json` (`CAMPAIGN_TMP = /srv/cycletmp`).

---

## 2. Current State — delivery complete and accepted

**Delivery directory (in place, all files verified byte-identical):**
`/root/samba/neutrino_power_cycle_outband_20261016_233643_136f68/`

| Artifact | Size | Status |
|---|---:|---|
| `CYCLE_REVIEW_REPORT.html` (main report, 4 tabs) | 5,038,237 b | MATCH · 0 CJK (pure English) |
| `CYCLE_VALIDATION_SPECIFICATION.html` (bilingual spec) | 518,409 b | MATCH · bilingual (12,267 CJK, per exception) |
| `CYCLE_REVIEW_REPORT.md` | 26,133 b | MATCH |
| `cycle_summary.txt` | 25,165 b | MATCH |
| `console.log` | 1,237,149 b | MATCH |
| `known_issues.md` | 377,578 b | MATCH |
| `new_issues.md` | 15,251,703 b | MATCH |
| `issue_policy.snapshot.md` / `neutrino_config.snapshot.sh` / `pre_orchestrator_dependencies.txt` | — | MATCH |
| `ETF1_n0..n3/` (evidence dirs) | 6,760 files each | MATCH (4×6,760 = 27,040 files) |
| `campaign.json` | — | **NOT in delivery (correct, per Decision A)** |
| `cycle_summary.json` | — | **NOT in delivery (correct, dropped from bundle)** |

**Acceptance checks (all passed):**
- 11 report files `cmp` byte-identical (source bundle ↔ delivery).
- 4 node evidence dirs have equal counts (6,760 / 6,760 / 6,760 / 6,760).
- All **3,362 local links** in the main report resolve inside the delivery
  directory (missing = 0), including `href="CYCLE_VALIDATION_SPECIFICATION.html"`
  → the spec file exists in the same directory, so the relative link opens.
- Main report has **0 CJK characters**; the spec HTML is the only file with
  Chinese (by design).
- Delivery directory contains **no** `campaign.json` and **no**
  `cycle_summary.json` (bundle-slimming is effective).

**Other pre-existing Samba data:** untouched (no add/remove/modify). `/root/samba`
is the CIFS mount `//10.33.34.22/eq3300/samba_tmp`. Other run directories (e.g.
`..._a4c310`, `..._c446f0`) and scattered old files (old 10/8
`CYCLE_REVIEW_REPORT.html`, `fullstress_...`, etc.) are preserved as-is.

**Verified this session (2026-10-17 23:35):**
- Delivery dir re-listed and consistent with the table above.
- `/srv/cycletmp/neutrino_power_cycle_outband_20261016_233643_136f68/` does
  **not** yet exist → journal move-out (see §4 / §5 P1) still pending for this run.

---

## 3. Analysis Findings (recon closed out)

1. **Total occurrences = 91,447**, matching the log total (37 merged cards summed).
   - Top: `ETF1_n2/eventlog` (20,039); Bottom: `ETF1_n2/eventlog` (135).
2. **37 cards vs 440 raw = the difference is caused by merging, not omission.**
   - 440 is the pre-merge raw issue line count; `merge_issues`
     (cycle_report.py:888) folds events with the same
     `(node, code/component, message)` into a single card → 37 merged cards.
   - The sum stays 91,447 (merging de-duplicates "cards", not "occurrences").
     **This is expected behavior.**
3. **`CYCLE_REVIEW_MERGED.html` vs `CYCLE_REVIEW_REPORT.html` = two versions of the
   same report, not two different artifacts.**
   - The current generator (`_write_reports`, cycle_report.py:1045) writes **only**
     `CYCLE_REVIEW_REPORT.html`.
   - `CYCLE_REVIEW_MERGED.html` (timestamp 22:23) is a **stale snapshot from before
     the merge feature was merged in**; the current `CYCLE_REVIEW_REPORT.html`
     (timestamp 22:52) is the latest.
   - Same size (5,038,237 b) is a coincidence; contents differ slightly (timestamp).
   - **Final delivery artifact = `CYCLE_REVIEW_REPORT.html`** (already delivered).
     `CYCLE_REVIEW_MERGED.html` is a leftover in the source bundle only.
4. **Report structure:** 4 tabs = `Nodes` / `Console` / `Problems to review`
   (37 cards) / `Issue review` (0 cards). Per-card occurrence sum on the Problems
   tab = 91,447.
5. **campaign.json journal location:**
   - Current `journal_path(root) = /srv/cycletmp/<bundle_dirname>/campaign.json`
     (cycle_report.py:26).
   - This run's 436 MB stale journal **still sits in the source bundle**
     (`campaigns/.../campaign.json`, produced 14:07, before the journal move-out
     commit) → the main cause of the 436 MB footprint.
   - `/srv/cycletmp/output/campaign.json` is a **different run** (2,417 b),
     unrelated to this run.

---

## 4. Decision A status & pending (journal move-out)

- `CAMPAIGN_TMP=/srv/cycletmp` is hardcoded; `journal_path` / `read_journal`
  (with in-bundle fallback) are in place.
- **This run has NOT yet had its journal written to
  `/srv/cycletmp/<run_id>/campaign.json`** (verified: the directory does not exist).
  It currently exists only in the source bundle.
  - Impact: `rebuild(<bundle>)` falls back to reading the 436 MB in-bundle file →
    slow but functional.
  - To let this run also benefit from move-out: copy the in-bundle `campaign.json`
    to `/srv/cycletmp/neutrino_power_cycle_outband_20261016_233643_136f68/`
    (**do NOT touch the delivery directory**; the journal is not part of the
    delivery). Details in §5 P1.

---

## 5. 續接點（下一步要做什麼）

> 交付「主體」已完成並通過驗收。以下為收尾／可選項，依優先級排序。
> **原則：動 source bundle（`campaigns/.../`）內的檔可以；動 `/root/samba` 其他既有資料不行；交付目錄已正確，別多餘改動。**

### 0. 本輪已確認的修正（先讀，避免重複誤判）
- **「push pending」是舊狀態**：本輪已驗證 `ts1` @ `9822dfd` == `origin/ts1`（`git fetch origin ts1` 遠端一致），且 `git push --dry-run origin ts1` 回「Everything up-to-date」。**代碼 push 已完成，不必再 push。**
- 真正「未入版控」的是工作區 5 個已修改檔 + 一堆 untracked（見 P2）。

### P0 — 清 source bundle（純省空間，不影響交付）
1. **外移本 run 的 436 MB journal 後，清掉 bundle 內殘留**（見 P1 第 1 步）：
   - `campaigns/.../campaign.json`（436,412,141 b）
   - `campaigns/.../cycle_summary.json`（46,004,747 b；HEAD 已「drop cycle_summary.json」，此為殘留）
   - 注意：這些都在 **source bundle**，**不在交付目錄**，刪不刪都不影響 Samba 交付。
2. **移除 bundle 內多餘／暫存檔**（純清理，不影響交付）：
   - `CYCLE_REVIEW_MERGED.html`（舊 snapshot，已被 `CYCLE_REVIEW_REPORT.html` 取代）
   - `CYCLE_REVIEW_LITE.html`
   - `CYCLE_REVIEW_REPORT.html.bak_before_english_20261017_225206`
   - 根目錄一堆 `*.bak_*`、`*.orig.bak`、`docs/SOP_cycle_zh-TW.html`
   - 判斷：都在 source / 工作區，**不在交付目錄**，刪不刪不影響交付。

### P1 — journal 外移「決策甲」收尾（若希望本 run 也吃到外移）
1. 建目錄並放入 journal：
   - `mkdir -p /srv/cycletmp/neutrino_power_cycle_outband_20261016_233643_136f68`
   - 把 bundle 內 `campaign.json` 複製過去（或下次 `write_reports` 自然會寫到該處）。
   - 完成後可接 P0 第 1 步 `rm campaigns/.../campaign.json` 省空間。
2. 確認 `read_journal` 對本 run 會**優先**讀 `/srv/cycletmp/<run_id>/campaign.json`（邏輯已在，跑一次 `rebuild` 驗證即可，會比讀 bundle 內 436 MB 快）。

### P2 — 未 commit 的變更（需決策；目前**無 push token**）
3. `git status` 顯示 5 個已修改、未 commit 的檔案：
   - `cycle_engine.py`（SEL 一律走 OOB；`command` 欄位改 `'sel list'`，功能性修正——reworked platform 無 `/dev/ipmi0`），**建議隨本輪一併 commit**。
   - `cycle_inventory_neutrino.csv`、`naboo_config.sh`、`neutrino_config.sh`（機器／網路調整，確認後再定）。
   - `dev/tests/test_cycle.py`（對應 SEL 走 OOB 的測試，建議隨 `cycle_engine.py` 一起 commit）。
4. **push 阻斷**：本環境 **沒有可用 push token**（`GITHUB_TOKEN` 不存在、`https://api.github.com/user` 回 401、remote 為匿名 https），故**目前無法 commit 後 push**。需使用者提供 push 憑證或改由有權限的機器執行。
5. 決定 `HANDOFF-*.md`、`docs/SOP_cycle_zh-TW.html` 等是否要入版控（目前 untracked）。

### P3 — 驗證／補強（選用）
6. 之後再跑 `rebuild`／`write_reports` 時，確認**新 run** 的 journal 直接落 `/srv/cycletmp/<run_id>/`、bundle 內不再產生 400+ MB 檔（驗證瘦身邏輯對新 run 真的生效）。
7. 交付端可選補一件：在交付目錄放一個 `MANIFEST.md`／checksums 讓接收方自驗（非需求，純加分；**加了也算「管理交付」，允許**，但需先與接收方確認要不要）。

### 不要做（避坑）
- ❌ 不要改 `/root/samba` 下**其他**既有檔／目錄。
- ❌ 不要把 `campaign.json`／`cycle_summary.json` 放進交付目錄。
- ❌ 不要動 `CYCLE_VALIDATION_SPECIFICATION.html` 的雙語（它是唯一保留中文的檔）。
- ❌ 別把 `CYCLE_REVIEW_MERGED.html` 當成第二份交付物（它是舊 snapshot，只在 source bundle）。
- ❌ 別重複「push」代碼——已推到 `origin/ts1` @ `9822dfd`；真正待辦是 commit＋push **工作區修改檔**（且需 push 憑證）。

---

## 6. Key File / Location Quick Reference

- Main report (delivery): `/root/samba/.../CYCLE_REVIEW_REPORT.html`
  (= source `CYCLE_REVIEW_REPORT.html`)
- Bilingual spec: `CYCLE_VALIDATION_SPECIFICATION.html` (present in delivery)
- Report generator: `cycle_report.py` (`write_reports`/`_write_reports`:997/1001,
  `rebuild`:1051, `journal_path`:26, `CAMPAIGN_TMP`:21)
- Merge / grouping: `merge_issues`(:888), `issue_cards_compact`(:916),
  `issue_key` (cycle_core.py:153), `_redfish_event_key`(:873), `_loop_ranges`(:849)
- Journal move-out: `CAMPAIGN_TMP=/srv/cycletmp` (hardcoded, Decision A)
- Samba mount: `//10.33.34.22/eq3300/samba_tmp → /root/samba` (CIFS, user eq3300)
- This run's source bundle: `campaigns/neutrino_power_cycle_outband_20261016_233643_136f68/`

## 7. Version Control Status

- Branch `ts1`, HEAD `9822dfd` (== origin/ts1 — **verified this session via
  `git fetch origin ts1`; code push is already complete**).
- Uncommitted (working tree, all `M`): `cycle_engine.py`,
  `cycle_inventory_neutrino.csv`, `dev/tests/test_cycle.py`, `naboo_config.sh`,
  `neutrino_config.sh`.
- Untracked: `HANDOFF-REPORT-SIZE-20261017.md` (+ its `.bak_*` copies), various
  `*.bak_*` / `*.orig.bak`, `docs/SOP_cycle_zh-TW.html`.
- Most recent commit: `9822dfd report: keep campaign.json outside the bundle,
  drop cycle_summary.json`.
