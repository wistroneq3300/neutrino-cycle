# 待辦：BMC 時間對齊 OS + EventLog 改為跑完才收

狀態：**尚未實作**（2026-10-31 記錄）
來源：Neutrino13 版本已先做過並實測，這裡記下做法與踩到的坑，方便回頭改 ts1。

---

## 需求

1. **每次開跑前**，把每個節點的 BMC 時間設定成該節點 OS 的時間。
2. **BMC EventLog 不要每階段收**，改成**整場跑完後一次性收**（不清除）。

理由：
- 這批 BMC 開機停在 **2000-01-22**，`EventLog` / `SEL` 的 `Created` 時間戳全是假的，
  事後追查事件時序完全沒用。
- EventLog 不清除就會累積歷史；每階段收一次只會得到 N 份重複的大檔案，
  看不出「哪筆是這次跑出來的」。

---

## 現況（ts1 現在的行為）

| 位置 | 目前做法 |
|---|---|
| `vera_cycle/engine/cycle_engine.py:1062` `_prepare_clean_state()` | PRE 階段前清 dmesg（`dmesg -C`）、讀後清 SEL、`collect_redfish(clear=True, history=True)` |
| `cycle_engine.py:1424` `collect_redfish()` | **每個 phase 都收** EventLog + SEL；`clear=True` 時先讀再清 |
| `cycle_engine.py:1164` `sel_command()` | SEL 走 OOB `ipmitool -I lanplus` |

**沒有** BMC 時間設定邏輯。

---

## 實作方式

### 1. BMC 時間對齊 OS

**關鍵坑：BMC 的 NTP 開著，Redfish 就不給寫 `DateTime`。**

實測錯誤訊息（Neutrino13 BMC）：

```
HTTP 400
Base.1.19.PropertyValueConflict
"The property 'DateTime' could not be written because its value would conflict
 with the value of the 'Managers/NetworkProtocol/NTPProcotolEnabled' property."
```

而且 `NTP` 的 `NTPServers` 是空陣列（`ProtocolEnabled: true` 但沒有時間來源），
所以 BMC 永遠停在 2000 年。

**`ipmitool sel time set` 也不能用**，這台 BMC 回傳中文在地化格式
（`2000年01月23日 01時27分07秒 CST`），ipmitool 解析失敗：

```
$ ipmitool ... sel time set "2026-10-30 17:15:43"
Specified time could not be parsed
```

**只能走 Redfish。**

順序：

```
1. 讀 OS UTC
   ssh <os> date -u '+%Y-%m-%dT%H:%M:%S+00:00'
2. 關 NTP
   PATCH /redfish/v1/Managers/BMC_0/NetworkProtocol
         {"NTP": {"ProtocolEnabled": false}}
3. 寫時間
   PATCH /redfish/v1/Managers/BMC_0
         {"DateTime": "2026-10-30T17:16:17+00:00"}
4. 讀回驗證
   GET   /redfish/v1/Managers/BMC_0  -> .DateTime
```

實測 4 台全部成功（HTTP 204），`DateTime` 與 OS 完全一致。

**注意**：
- Manager id 這 4 台都是 `BMC_0`，但 ts1 應該沿用既有的 `_redfish_discover()`
  去取得 system/manager id，不要寫死。
- 關掉 NTP 是 side effect。若要還原，跑完後把 `ProtocolEnabled` 設回 `true`。
  目前選擇是**不還原**（每次開跑前重設即可）。

### 2. EventLog 改成跑完才收

EventLog **不清除**，所以跑完讀到的是整段歷史。要認出「這次跑的」得靠 Id 界線：

```
開跑前：
  GET /redfish/v1/Systems/<system_id>/LogServices/EventLog/Entries
  記下目前最大 Id  →  baseline

跑完後：
  再 GET 一次全量  →  存 post_<node>_eventlog.json
  Id > baseline 的才列成「本次新增」→ 存 post_<node>_eventlog_new.txt
```

**不要用時間戳過濾**：BMC 時鐘沒對時之前時間戳不可信。
即使做了上面第 1 點的對時，還是建議用 Id，因為對時之後才開始有意義。

### 3. 收的位置

- baseline：開跑前，跟 `_prepare_clean_state()` 同一階段（但**不要清 EventLog**）
- 收尾：整個 campaign / run 全部結束後，**只呼叫一次**

ts1 目前 `collect_redfish()` 綁在 phase 上（PRE/cycle/POST 各一次）。
要改成跑完才收，得把 EventLog 這部分從 per-phase 流程裡拆出來，
或用一個 `final_collect=True` 之類的參數繞過。

---

## 參考實作（Neutrino13 版，已實測）

檔案：`/root/samba/Sheng/for neutrino rel/neutrino-cycle-python/neutrino_cycle.py`

| 函式 | 作用 |
|---|---|
| `redfish(target, path, method, body, password)` | 單次 Redfish 呼叫，回傳 `(http_code, body)` |
| `sync_bmc_time(target, os_pw, bmc_pw, log)` | 讀 OS 時間 → 關 NTP → 寫 DateTime → 讀回驗證 |
| `eventlog_baseline(targets, ev_dir, bmc_pw, log)` | 記下每台最大 EventLog Id |
| `eventlog_after_run(targets, ev_dir, bmc_pw, baseline, log)` | 跑完全量讀一次，用 Id 過濾出本次新增 |
| `clear_before_start(targets, ...)` | 並行：對時 + `dmesg -C` + SEL 讀後清 |

### 實測結果（Neutrino13，4 台）

```
time Neutrino13/n0  bmc=2026-10-30T17:19:54+00:00 os=2026-10-30T17:19:54+00:00
time Neutrino13/n1  bmc=2026-10-30T17:19:54+00:00 os=2026-10-30T17:19:54+00:00
time Neutrino13/n2  bmc=2026-10-30T17:19:54+00:00 os=2026-10-30T17:19:54+00:00
time Neutrino13/n3  bmc=2026-10-30T17:19:54+00:00 os=2026-10-30T17:19:54+00:00
eventlog Neutrino13/n0  baseline_id=1 (http 200)
```

原本 BMC 是 `2000-01-22T17:27:17+00:00`。

**並行**：4 台一起做，32 秒 → 6.6 秒（含 precheck）。

---

## 待決事項

- [ ] 跑完後要不要把 NTP 還原成 `true`
- [ ] EventLog 收尾要不要也並行（目前是逐台）
- [ ] 收尾的 EventLog 要不要進 HTML 報告，或只存 evidence
      （Neutrino13 版是**只存 evidence，不判斷 PASS/FAIL、不進報告**）

---

# 補充（2026-10-31）：改用 NTP server，不用每次手動 PATCH 時間

上面「手動 PATCH DateTime」的做法可以用，但**每次開跑前都要重設**，而且
BMC 一旦重開又回到 2000 年。實測後改用 **NTP server** 更好：

- BMC 的 NTP 一直開著（`ProtocolEnabled: true`），只是 `NTPServers` 是空的
- 只要把 `NTPServers` 指向同網段一台會發時間的機器，BMC 就自己對時
- 不需要關 NTP、不需要每次寫 DateTime

## 做法（Neutrino13，已在 4 台做完並驗證）

### 1. OS 開啟 NTP server

這 4 台的 chrony 已經在對外同步（`pool.ntp.org`，Stratum 3，誤差 ~0.2ms），
只是沒有 `allow` 規則，所以不能服務別人。加一個 conf.d 檔案即可：

```bash
cat > /etc/chrony/conf.d/lab-ntp-server.conf <<'EOF'
# Serve time to the BMCs on the same lab subnet. The BMCs have NTP enabled
# with no server list, so they sit at 2000-01-01 until one is provided.
allow 10.36.72.0/24
EOF
systemctl restart chrony
```

驗證：

```bash
systemctl is-active chrony                      # active
ss -lunp | grep ":123"                          # 0.0.0.0:123 chronyd
chronyc tracking                                # Stratum 3, offset < 1ms
```

**注意**：Ubuntu 24.04+ 的 chrony 改用 `sources.d/` 與 `conf.d/`，
主 `chrony.conf` 只有 `sourcedir` / `confdir` 指令。`allow` 放 `conf.d/*.conf`。

### 2. BMC 指向該 NTP server

```bash
curl -sk -u root:0penBmc -X PATCH -H "Content-Type: application/json" \
  -d '{"NTP":{"ProtocolEnabled":true,"NTPServers":["10.36.72.232"]}}' \
  https://<bmc_ip>/redfish/v1/Managers/BMC_0/NetworkProtocol
```

BMC ↔ OS 配對（同 node）：

| BMC | NTP server (同 node OS) |
|---|---|
| 10.36.72.233 | 10.36.72.232 |
| 10.36.72.235 | 10.36.72.234 |
| 10.36.72.237 | 10.36.72.236 |
| 10.36.72.239 | 10.36.72.238 |

### 3. 驗證

把 BMC 時間刻意設回 2000-01-01 再開 NTP，觀察它會自己跳回正確時間：

```
設定前: 2000-01-01T00:00:00+00:00
開啟 NTP 後 12 秒內: 2026-10-30T17:24:38+00:00   ← 立即對上
```
4 台 BMC 全部成功。

## 對 ts1 的意義

**比手動 PATCH 好**：

| | 手動 PATCH DateTime | NTP server |
|---|---|---|
| 開跑前要做的事 | 關 NTP → 寫時間 → 驗證 | **不用做** |
| BMC 重開後 | 回到 2000 年 | 自己對時 |
| 精確度 | 對一次 | 持續同步 |

**所以 ts1 的實作可以簡化成**：
1. 開跑前**檢查** BMC 的 `NTPServers` 是否為空 / 時間是否合理
   - 若為空或明顯偏差 → 設 `NTPServers` 指向同 node 的 OS IP
   - （可選）順便檢查 OS 的 chrony 是否有 `allow` 規則
2. **不需要**關 NTP、不需要寫 DateTime
3. EventLog 照原計畫：跑完收一次，用 Id 過濾

若某個環境的 OS 不能當 NTP server，才退回手動 PATCH DateTime 的做法。

## 已做的系統變更（Neutrino13 4 台）

- `/etc/chrony/conf.d/lab-ntp-server.conf`（新增，內容只有 `allow 10.36.72.0/24`）
- `systemctl restart chrony`
- BMC `NTPServers` 設為同 node OS IP，`ProtocolEnabled: true`

要還原：

```bash
rm /etc/chrony/conf.d/lab-ntp-server.conf && systemctl restart chrony
curl ... -X PATCH -d '{"NTP":{"ProtocolEnabled":false,"NTPServers":[]}}' .../NetworkProtocol
```
