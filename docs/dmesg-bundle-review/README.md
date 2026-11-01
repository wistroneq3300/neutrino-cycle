# DMESG_BUNDLE review request

Campaign: `Neutrino13_power_cycle_outband_20261101_032555_4631ac`
Tray: Neutrino13, 4 nodes, `power_cycle` / `outband`, 100-loop limit.
Loops actually completed: n0=41, n1=56, n2=87, n3=87 (269 loops total).

## Why this file exists

Our report raises `DMESG_BUNDLE` as **FAIL** on **269 of 269 loops**. Three real
events happened in this campaign (two nodes lost, one PCIe link downtrain), so a
code that fires on every loop on every machine is drowning them. Before we
downgrade it, we want someone to check the claim: **are these boot-time
messages, or real faults?**

We are not asking for a judgement based on the message text alone. Below is the
evidence we collected, in three independent forms.

## Evidence 1 — frequency

18 distinct families behind all 17,612 occurrences. If these were fault
events they would not appear on ~100% of boots on 4 separate machines.

## Evidence 2 — placement in the boot log

Every family first appears between **T+12s and T+42s** of kernel time, while the
same kernel boot is still enumerating PCI and starting drivers. The last line of
the same log is at T+134s (`MFT device name created`). These messages are part of
the boot path, not something that happened while the machine was running a test
loop.

## Evidence 3 — the one message we could trace to source

`PCI: OF: of_root node is NULL, cannot create PCI host bridge node` is:

```c
/* drivers/pci/of.c */
static void of_pci_make_host_bridge_node(...)
{
        ...
        if (!of_root) {
                pr_debug("of_root node is NULL, cannot create PCI host bridge node\n");
                return;
        }
```

`pr_debug` is a debug-level print, and the `return` is a normal early exit — the
function simply skips creating an OpenFirmware node for a host bridge. It appears
in our captures only because `dmesg` reads the whole ring buffer regardless of
console loglevel (`printk` is `4 4 1 7`, i.e. console shows err and above only).

## The table

Rate = occurrences per loop. `1.00x` = once per boot on that host (expected).
`0.01x`-value rows are **not** uniform and are called out separately below.

| # | Family | n0 | n1 | n2 | n3 | 1st stamp |
|---|---|---|---|---|---|---|
| 1 | `pci <BDF>: bridge window [io  size <hex>]: failed to assign` | 35.12x | 35.36x | 36.00x | 36.00x | [12.11s] |
| 2 | `PCI: OF: of_root node is NULL, cannot create PCI host bridge node` | 16.59x | 16.70x | 17.00x | 17.00x | [12.09s] |
| 3 | `pci <BDF>: BAR <N> [io  size <hex>]: failed to assign` | 1.95x | 1.96x | 2.00x | 2.00x | [12.13s] |
| 4 | `ipmi_ssif i2c-IPI0001:<N>: ipmi_ssif: Unable to clear message flags: <N> <N> c1` | 1.95x | 1.96x | 2.00x | 2.00x | [21.46s] |
| 5 | `ipmi_si: Unable to find any System Interface(s)` | 1.39x | 1.43x | 1.51x | 1.52x | [21.30s] |
| 6 | `systemd-journald[<PID>]: File /var/log/journal/4c88130fa7414d67b4615f64fb49c9eb/system.journal corrupted ` | 0.98x | 0.98x | 1.00x | 1.00x | — |
| 7 | `ipmi_ssif dmi-ipmi-ssif.<N>: probe with driver ipmi_ssif failed with error -<N>` | 0.98x | 0.98x | 1.00x | 1.00x | [20.96s] |
| 8 | `mlx_compat: module verification failed: signature and/or required key missing - tainting kernel` | 0.98x | 0.98x | 1.00x | 1.00x | [21.18s] |
| 9 | `mlx5_core <BDF>: wait_fw_init:<N>:(pid <N>): Waiting for FW pre-initializing, timeout abort in 100s (<hex` | 0.98x | 0.98x | 1.00x | 1.00x | [42.48s] |
| 10 | `mlx5_core <BDF>: wait_fw_init:<N>:(pid <N>): Waiting for FW pre-initializing, timeout abort in 79s (<hex>` | 0.98x | 0.98x | 1.00x | 1.00x | [42.48s] |
| 11 | `mlx5_core <BDF>: wait_fw_init:<N>:(pid <N>): Waiting for FW pre-initializing, timeout abort in 59s (<hex>` | 0.98x | 0.98x | 1.00x | 1.00x | [42.48s] |
| 12 | `mlx5_core <BDF>: wait_fw_init:<N>:(pid <N>): Waiting for FW pre-initializing, timeout abort in 39s (<hex>` | 0.95x | 0.86x | 0.98x | 0.94x | [42.48s] |
| 13 | `ipmi_ssif i2c-IPI0001:<N>: IPMI message handler: device id fetch failed: <hex>` | — | 0.02x | — | 0.01x | [23.12s] |
| 14 | `ipmi_ssif i2c-IPI0001:<N>: IPMI message handler: Unable to get the device id: -<N>` | — | 0.02x | — | 0.01x | [23.12s] |
| 15 | `ipmi_ssif i2c-IPI0001:<N>: ipmi_ssif: Unable to register device: error -<N>` | — | 0.02x | — | 0.01x | [22.67s] |
| 16 | `ipmi_ssif i2c-IPI0001:<N>: ipmi_ssif: Unable to start IPMI SSIF: -<N>` | — | 0.02x | — | 0.01x | [22.67s] |
| 17 | `ipmi_ssif i2c-IPI0001:<N>: probe with driver ipmi_ssif failed with error -<N>` | — | 0.02x | — | 0.01x | — |
| 18 | `mlx5_core <BDF>: wait_fw_init:<N>:(pid <N>): Waiting for FW pre-initializing, timeout abort in 19s (<hex>` | — | — | — | 0.01x | [42.48s] |

## What we think, and what we are unsure about

**Confident these are normal:** rows 1-12. Each is either a `pr_debug`, a
successful-boot-only message, or a driver advisory that appears exactly once per
boot on all four machines. The PCI `bridge window ... failed to assign` and
`of_root node is NULL` lines belong to the same OpenFirmware host-bridge code
path and always fire together at T+12s.

**Not sure these are normal:** rows 13-18. They appear on only 3 loops out of
269 (`n1/loop0005`, `n3/loop0018`, `n3/loop0046`):

- `ipmi_ssif ... Unable to get the device id` / `Unable to register device` /
  `Unable to start IPMI SSIF`
- `mlx5_core ... wait_fw_init ... timeout abort in 19s`

These are low-rate and may be a genuinely different path (IPMI SSIF probe retry,
or an mlx5 firmware init that ran shorter). We would like these looked at
separately rather than swept into a blanket "boot noise" rule.

## Questions

1. Are rows 1-12 safe to treat as expected on every boot of this platform, so
   they should not raise a finding?
2. Are rows 13-18 normal boot variance (retry that succeeds on the next
   attempt), or do they indicate a real intermittent issue worth keeping as a
   finding?
3. Is there a more reliable discriminator than the message text — e.g. reading
   `/sys/kernel/debug/dynamic_debug/control` to see whether a message is
   `pr_debug`-gated, or checking whether the PCI bridge ended up functional
   (`lspci` lists the device, no error counters) after the message appeared?

## Reproducing

Everything above is derived from the per-loop `report.json` and
`dmesg_clear.txt` files in the campaign directory (not included here; the raw
text is customer data). The extraction script is in `extract.py` next to this
file.
