# DMESG_BUNDLE families

Loops: Neutrino13_n0=41, Neutrino13_n1=56, Neutrino13_n2=87, Neutrino13_n3=87

Rate = occurrences per loop. 1.00x means once per boot.

| # | Family | Neutrino13_n0 | Neutrino13_n1 | Neutrino13_n2 | Neutrino13_n3 | 1st stamp |
|---|---|---|---|---|---|---|
| 1 | `pci <BDF>: bridge window [io  size <hex>]: failed to assign` | 35.12x | 35.36x | 36.00x | 36.00x | [12.11s] |
| 2 | `PCI: OF: of_root node is NULL, cannot create PCI host bridge node` | 16.59x | 16.70x | 17.00x | 17.00x | [12.09s] |
| 3 | `pci <BDF>: BAR <N> [io  size <hex>]: failed to assign` | 1.95x | 1.96x | 2.00x | 2.00x | [12.13s] |
| 4 | `ipmi_ssif i2c-IPI0001:<N>: ipmi_ssif: Unable to clear message flags: <N> <N> c1` | 1.95x | 1.96x | 2.00x | 2.00x | [21.46s] |
| 5 | `ipmi_si: Unable to find any System Interface(s)` | 1.39x | 1.43x | 1.51x | 1.52x | [21.30s] |
| 6 | `systemd-journald[<PID>]: File /var/log/journal/4c88130fa7414d67b4615f64fb49c9eb/system.journal corrupted ` | 0.98x | 0.98x | 1.00x | 1.00x | - |
| 7 | `ipmi_ssif dmi-ipmi-ssif.<N>: probe with driver ipmi_ssif failed with error -<N>` | 0.98x | 0.98x | 1.00x | 1.00x | [20.96s] |
| 8 | `mlx_compat: module verification failed: signature and/or required key missing - tainting kernel` | 0.98x | 0.98x | 1.00x | 1.00x | [21.18s] |
| 9 | `mlx5_core <BDF>: wait_fw_init:<N>:(pid <N>): Waiting for FW pre-initializing, timeout abort in 100s (<hex` | 0.98x | 0.98x | 1.00x | 1.00x | [42.48s] |
| 10 | `mlx5_core <BDF>: wait_fw_init:<N>:(pid <N>): Waiting for FW pre-initializing, timeout abort in 79s (<hex>` | 0.98x | 0.98x | 1.00x | 1.00x | [42.48s] |
| 11 | `mlx5_core <BDF>: wait_fw_init:<N>:(pid <N>): Waiting for FW pre-initializing, timeout abort in 59s (<hex>` | 0.98x | 0.98x | 1.00x | 1.00x | [42.48s] |
| 12 | `mlx5_core <BDF>: wait_fw_init:<N>:(pid <N>): Waiting for FW pre-initializing, timeout abort in 39s (<hex>` | 0.95x | 0.86x | 0.98x | 0.94x | [42.48s] |
| 13 | `ipmi_ssif i2c-IPI0001:<N>: IPMI message handler: device id fetch failed: <hex>` | - | 0.02x | - | 0.01x | [23.12s] |
| 14 | `ipmi_ssif i2c-IPI0001:<N>: IPMI message handler: Unable to get the device id: -<N>` | - | 0.02x | - | 0.01x | [23.12s] |
| 15 | `ipmi_ssif i2c-IPI0001:<N>: ipmi_ssif: Unable to register device: error -<N>` | - | 0.02x | - | 0.01x | [22.67s] |
| 16 | `ipmi_ssif i2c-IPI0001:<N>: ipmi_ssif: Unable to start IPMI SSIF: -<N>` | - | 0.02x | - | 0.01x | [22.67s] |
| 17 | `ipmi_ssif i2c-IPI0001:<N>: probe with driver ipmi_ssif failed with error -<N>` | - | 0.02x | - | 0.01x | - |
| 18 | `mlx5_core <BDF>: wait_fw_init:<N>:(pid <N>): Waiting for FW pre-initializing, timeout abort in 19s (<hex>` | - | - | - | 0.01x | [42.48s] |
