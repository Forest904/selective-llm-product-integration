# Dataset Candidate Report

M1 ranks candidate product domains with hard assignment gates first and a documented
selection score second.

Score table artifact: `artifacts/tables/m1_selection_score_table.parquet`

| Vertical | Sources | Records | Entities | Positive pairs | Fusion conflicts | Gate | Score |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| notebook | 27 | 23167 | 208 | 2595 | 0 | False | 62.1982 |
| monitor | 26 | 16662 | 232 | 10017 | 0 | False | 58.3630 |
| camera | 24 | 29787 | 103 | 70596 | 0 | False | 33.7075 |

## Recommendation

Selected candidate: `notebook`.

## Benchmark Fallback Watchpoint

No candidate satisfies every assignment gate with the currently available evidence. Manually place and profile local Alaska records before relaxing the benchmark choice.

