# vera-cpu-rack-cycle / branch ts1 — 要修項目動作表

基準 commit：`4309c8d` ／ 審查日：2026-10-23 ／ 測試：373 passed, 1 skipped

---

## 一、本次已修（已完成，附測試）

| # | 嚴重度 | 檔案 : 位置 | 問題 | 動作 | 測試 | 狀態 |
|---|---|---|---|---|---|---|
| 1 | 高 | `cycle_engine.py` `_redfish_loop_delta`（~1215）、`cycle_core.py` `_redfish_delta_ids`（~996）／ `aggregate_issues`（~1044） | EventLog 與 SEL 共用 id 會互相誤判 NEW | 新增服務限定 `redfish_delta_ids`，比對用「服務+id」，相容舊扁平欄位 | `test_redfish_failures.CrossServiceDeltaIdTests`（3） | ✅ 已修 |
| 2 | 高 | `cycle_report.py` `_pci_devices`（~510） | 舊格式 `pci` 字串對照表讓離線 rebuild 崩潰 | 非 dict 值包成 `{'ids': ...}` | `test_report_semantics.test_legacy_string_pci_map_still_renders` | ✅ 已修 |
| 3 | 中 | `cycle_dmesg.py` `BUNDLE_BENIGN`（~46） | 裸 `nvme/mlx5/NVRM/EDAC` 當續行會吞掉真錯誤 | 只留 `AER:` / `PCIe Bus Error:` | `test_dmesg_bundle`（2） | ✅ 已修 |
| 4 | 中 | `cycle_dmesg.py` `_bundle_event`（~71） | BDF 被遮罩 → 第二張卡漏抓 | entry 保留 BDF、fingerprint 正規化 | `test_dmesg_bundle`（2） | ✅ 已修 |
| 5 | 中 | `cycle_report.py` `_dmesg_severity`（~259） | APEI-only 時 `bundle=None` 解參考風險 | 空項跳過 | `test_dmesg_package_html_survives_every_capture_shape` | ✅ 已修 |
| 6 | 中 | `neutrino_cycle.py` `campaign` finally | render 失敗把 COMPLETE 誤改 INCOMPLETE | 終態先 `write_journal` + `verdict_fixed` 旗標 | `test_run2_recovery` | ✅ 已修 |
| 7 | 中 | `cycle_report.py` split / `_finding_html*` | `|` 截斷、HTML 卡片顯示 raw component | `split('|',2)`；改用 `display_component` | `MessageWithPipeTests`、`display_component` 系列 | ✅ 已修 |
| 8 | 低 | `stop_cycle.sh` `terminate_holders` | `--force <id>` 跨 campaign 誤停 | `run_id` 限定 holder | 靜態檢查 + `bash -n` | ✅ 已修 |

## 二、本次未修（分析後決定不動 / 待決策）

| # | 嚴重度 | 檔案 : 位置 | 議題 | 建議 | 狀態 |
|---|---|---|---|---|---|
| 9 | 低 | `cycle_engine.py` `identity`（~252） | hostname 不符目前是 WARN | **維持 WARN**（硬擋會與 inventory placeholder 需求衝突、打字錯誤會鎖全批）；若要嚴，改為節點級 strict | 依使用者指示不動 |
| 10 | 低 | legacy journal | 舊 journal 只有扁平 id，仍有理論碰撞 | 可選一次性 migration（建議先不做） | 待決策 |
| 11 | 資訊 | `stop_cycle.sh` 非 force 路徑 | `--status` 與 `$@` 傳遞 | 已確認 `STATUS` 分支提前 exit，無誤傳 | 無需修 |

## 三、最後階段：目錄重整（未做，待使用者確認後執行）

| # | 項目 | 現況 | 建議 | 風險 |
|---|---|---|---|---|
| 12 | `ux-bak/` | 5 個舊 TUI 備份（未追蹤） | 移到 `dev/backup/` 或加進 `.gitignore` / 刪除 | 低 |
| 13 | `.agent_notes/` | 本次審查快照（patch + head，未追蹤） | 保留作 rollback 點，或於 PR 前移除 | 低 |
| 14 | `cycle_report_lite.py` | 成熟工具 | **不列入重構**（依使用者指示） | — |
| 15 | 根目錄文件/快照 | `*.snapshot.*`、`ANALYSIS_*.md` 在 campaign 內 | 不動 campaign 內容 | — |

## 四、驗證與交付狀態

| 項目 | 結果 |
|---|---|
| 全部測試 | 373 passed, 1 skipped |
| `py_compile`（全部 .py） | OK |
| `bash -n stop_cycle.sh` | OK |
| 真實 campaign rebuild（有 journal 者） | 13 / 13 成功 |
| Evidence 連結缺失 | 0 / 91,447 |
| merge 重複議題 | 0 |
| 實體設備狀態變更 | 無（全程唯讀 / 暫存目錄） |
| push / merge / 動 main | 無 |
| PR | 尚未開（依規定需先問使用者） |
