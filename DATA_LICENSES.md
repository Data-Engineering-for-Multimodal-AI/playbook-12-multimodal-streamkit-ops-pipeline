# Data licenses

This file lists the datasets and models this playbook uses, where they come from, and their licenses. The code in this repository is MIT-licensed. That license does not cover third-party data or models; each one keeps its own license, listed below.

## Datasets

| Dataset | Source | License | In this repo |
|---|---|---|---|
| Sample case `20240115` (pod metrics, log signals, KPI and fault labels) | Synthetic, committed with the first edition. How it was generated is not recorded (see Notes) | MIT (this repository) | `data/20240115/` (2.9 MB) |
| LEMMA-RCA, Cloud Computing Preprocessed | [Hugging Face: Lemma-RCA-NEC/Cloud_Computing_Preprocessed](https://huggingface.co/datasets/Lemma-RCA-NEC/Cloud_Computing_Preprocessed), pinned revision `03f82a2c` | [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/), per the Hugging Face dataset card | No. Downloaded by `make data` (`python download_data.py --case 20240115`) into `data/lemma-rca/20240115/`: a 193 MB download, of which 37 MB is kept. Other cases with `--case` |

## Models

| Model | Source | License | How it's used |
|---|---|---|---|
| An OpenAI-compatible LLM (optional; `gpt-4o` by default) | Whatever `LLM_BASE_URL` points to (OpenAI by default) | Hosted service; use is governed by the provider's terms | Optional root-cause analysis in `pipeline/plan.py`, used only when `LLM_API_KEY` is set. Set the model with `LLM_MODEL`. Without a key the analysis is rule-based |

## Notes

- LEMMA-RCA is CC BY-NC 4.0 (non-commercial). That license, not this repository's MIT license, governs use of the downloaded data.
- The bundled sample is not LEMMA-RCA data. The README says its values are seeded random numbers and 7 of its 8 pod names are made up; the 8th pod borrows its name and fault label from LEMMA-RCA case 20240115.

## Citations

- LEMMA-RCA: L. Zheng, Z. Chen, D. Wang, C. Deng, R. Matsuoka and H. Chen, "LEMMA-RCA: A Large Multi-modal Multi-domain Dataset for Root Cause Analysis", arXiv:2406.05375, 2024.
