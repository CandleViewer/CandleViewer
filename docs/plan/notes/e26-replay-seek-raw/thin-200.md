Label: **SYNTHETIC 200-depth day (no E16 recorded day exists); laptop, not WSL/docker target** (span 4000 s, profile thin, x21.6 to 24 h)

| source                                                  | interval s | window      | frames | p50 ms | p95 ms | max ms | anchor | delta  | builder | warmup | book ok |
| ------------------------------------------------------- | ---------- | ----------- | ------ | ------ | ------ | ------ | ------ | ------ | ------- | ------ | ------- |
| cold (Parquet, pyarrow)                                 | 300        | busy_window | 2992   | 432.23 | 637.88 | 637.88 | 9.17   | 297.06 | 21.12   | 98.78  | True    |
| cold (Parquet, pyarrow)                                 | 300        | calm_window | 2990   | 360.17 | 501.81 | 501.81 | 7.83   | 291.15 | 19.82   | 26.18  | True    |
| cold (Parquet, pyarrow)                                 | 60         | busy_window | 600    | 196.2  | 210.32 | 210.32 | 7.24   | 99.68  | 27.66   | 60.69  | True    |
| cold (Parquet, pyarrow)                                 | 60         | calm_window | 598    | 67.92  | 71.12  | 71.12  | 6.64   | 48.31  | 12.41   | 1.06   | True    |
| cold (Parquet, pyarrow)                                 | 30         | busy_window | 300    | 216.26 | 319.95 | 319.95 | 9.55   | 111.83 | 26.77   | 98.27  | True    |
| cold (Parquet, pyarrow)                                 | 30         | calm_window | 298    | 85.41  | 105.07 | 105.07 | 8.49   | 57.99  | 12.93   | 1.58   | True    |
| hot STAND-IN (in-memory, not QuestDB)                   | 300        | busy_window | 2992   | 309.96 | 373.59 | 373.59 | 2.19   | 228.58 | 14.01   | 68.13  | True    |
| hot STAND-IN (in-memory, not QuestDB)                   | 300        | calm_window | 2990   | 209.58 | 222.88 | 222.88 | 2.38   | 169.93 | 13.79   | 22.05  | True    |
| hot STAND-IN (in-memory, not QuestDB)                   | 60         | busy_window | 600    | 172.52 | 232.63 | 232.63 | 2.07   | 93.33  | 24.87   | 58.01  | True    |
| hot STAND-IN (in-memory, not QuestDB)                   | 60         | calm_window | 598    | 63.38  | 73.48  | 73.48  | 3.08   | 43.01  | 17.02   | 0.26   | True    |
| hot STAND-IN (in-memory, not QuestDB)                   | 30         | busy_window | 300    | 117.95 | 121.51 | 121.51 | 2.26   | 50.45  | 16.36   | 47.96  | True    |
| hot STAND-IN (in-memory, not QuestDB)                   | 30         | calm_window | 298    | 35.5   | 36.42  | 36.42  | 2.44   | 20.75  | 11.95   | 0.17   | True    |
| cold (Parquet, pyarrow) + collapsed deltas (mitigation) | 300        | busy_window | 504    | 110.82 | 126.57 | 126.57 | 5.39   | 29.74  | 10.06   | 60.18  | True    |
| cold (Parquet, pyarrow) + collapsed deltas (mitigation) | 300        | calm_window | 461    | 65.28  | 72.52  | 72.52  | 6.45   | 27.26  | 11.18   | 19.65  | True    |
| cold (Parquet, pyarrow) + collapsed deltas (mitigation) | 60         | busy_window | 461    | 92.23  | 95.62  | 95.62  | 5.55   | 25.83  | 17.96   | 42.56  | True    |
| cold (Parquet, pyarrow) + collapsed deltas (mitigation) | 60         | calm_window | 428    | 41.12  | 43.56  | 43.56  | 5.96   | 22.83  | 11.31   | 1.0    | True    |
| cold (Parquet, pyarrow) + collapsed deltas (mitigation) | 30         | busy_window | 431    | 91.43  | 103.7  | 103.7  | 6.14   | 23.54  | 12.43   | 43.34  | True    |
| cold (Parquet, pyarrow) + collapsed deltas (mitigation) | 30         | calm_window | 418    | 38.6   | 40.38  | 40.38  | 6.45   | 22.46  | 8.63    | 0.99   | True    |
