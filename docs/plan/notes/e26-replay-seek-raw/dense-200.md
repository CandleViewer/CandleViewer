Label: **SYNTHETIC 200-depth day (no E16 recorded day exists); laptop, not WSL/docker target** (span 910 s, profile dense, x94.9 to 24 h)

| source                                                  | interval s | window      | frames | p50 ms  | p95 ms   | max ms   | anchor | delta   | builder | warmup | book ok |
| ------------------------------------------------------- | ---------- | ----------- | ------ | ------- | -------- | -------- | ------ | ------- | ------- | ------ | ------- |
| cold (Parquet, pyarrow)                                 | 300        | busy_window | 3000   | 6000.05 | 8582.11  | 8582.11  | 4.61   | 5655.26 | 35.19   | 307.21 | True    |
| cold (Parquet, pyarrow)                                 | 300        | calm_window | 3000   | 5211.89 | 7855.93  | 7855.93  | 4.45   | 4996.03 | 24.14   | 161.95 | True    |
| cold (Parquet, pyarrow)                                 | 60         | busy_window | 600    | 1859.46 | 3730.73  | 3730.73  | 4.67   | 1612.27 | 56.48   | 175.77 | True    |
| cold (Parquet, pyarrow)                                 | 60         | calm_window | 600    | 991.45  | 1178.44  | 1178.44  | 4.9    | 927.83  | 58.05   | 1.15   | True    |
| cold (Parquet, pyarrow)                                 | 30         | busy_window | 300    | 999.68  | 1026.66  | 1026.66  | 4.35   | 792.82  | 22.92   | 174.49 | True    |
| cold (Parquet, pyarrow)                                 | 30         | calm_window | 300    | 515.12  | 634.14   | 634.14   | 4.85   | 474.23  | 34.63   | 1.2    | True    |
| hot STAND-IN (in-memory, not QuestDB)                   | 300        | busy_window | 3000   | 9789.89 | 10275.97 | 10275.97 | 2.08   | 9354.02 | 22.88   | 324.44 | True    |
| hot STAND-IN (in-memory, not QuestDB)                   | 300        | calm_window | 3000   | 7520.35 | 17804.38 | 17804.38 | 2.42   | 7331.46 | 16.84   | 167.19 | True    |
| hot STAND-IN (in-memory, not QuestDB)                   | 60         | busy_window | 600    | 2857.5  | 3731.81  | 3731.81  | 2.17   | 2624.33 | 51.07   | 191.03 | True    |
| hot STAND-IN (in-memory, not QuestDB)                   | 60         | calm_window | 600    | 1316.87 | 1346.42  | 1346.42  | 2.25   | 1251.69 | 62.75   | 0.28   | True    |
| hot STAND-IN (in-memory, not QuestDB)                   | 30         | busy_window | 300    | 1387.21 | 1556.47  | 1556.47  | 2.15   | 1172.68 | 28.33   | 184.26 | True    |
| hot STAND-IN (in-memory, not QuestDB)                   | 30         | calm_window | 300    | 711.8   | 821.46   | 821.46   | 2.46   | 667.71  | 47.05   | 0.29   | True    |
| cold (Parquet, pyarrow) + collapsed deltas (mitigation) | 300        | busy_window | 635    | 928.3   | 1327.98  | 1327.98  | 5.55   | 465.09  | 22.36   | 455.93 | True    |
| cold (Parquet, pyarrow) + collapsed deltas (mitigation) | 300        | calm_window | 880    | 557.36  | 781.27   | 781.27   | 5.17   | 358.3   | 14.39   | 173.79 | True    |
| cold (Parquet, pyarrow) + collapsed deltas (mitigation) | 60         | busy_window | 610    | 384.04  | 410.2    | 410.2    | 4.68   | 144.54  | 47.67   | 177.0  | True    |
| cold (Parquet, pyarrow) + collapsed deltas (mitigation) | 60         | calm_window | 619    | 158.57  | 184.84   | 184.84   | 5.44   | 83.55   | 68.7    | 1.32   | True    |
| cold (Parquet, pyarrow) + collapsed deltas (mitigation) | 30         | busy_window | 566    | 272.92  | 281.88   | 281.88   | 4.41   | 69.97   | 25.58   | 169.3  | True    |
| cold (Parquet, pyarrow) + collapsed deltas (mitigation) | 30         | calm_window | 594    | 93.18   | 104.22   | 104.22   | 4.83   | 50.56   | 36.43   | 1.13   | True    |
