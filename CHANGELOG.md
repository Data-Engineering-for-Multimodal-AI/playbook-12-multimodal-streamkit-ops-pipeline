# Changelog

## 2026.10.1 (2026-10-27)

Checked against the book (Early Release, pages 496–500).

### Added
- All six LEMMA-RCA Cloud Computing cases run, as the book's "Extending the Playbook" says (page 499).
  The downloader converts each case's own pod metrics, reads its SLI (error rate, latency or hourly
  cost), time zone and root cause, and the incident threshold follows the SLI. Results for every case
  are in the README; CI runs the four new cases.
- `.env.example` with the LLM variables.
- `python run_pipeline.py` without `--case` prints the `--case` command when the default case has been
  downloaded (the book runs it right after the download).

### Changed
- README: page numbers; the six-case results; notes on the book's `cd streamkit-ops-playbook`,
  `ANTHROPIC_API_KEY` and dataset licence (page 497 says CC BY-ND 4.0; the dataset card says CC BY-NC 4.0).

## 2026.10 (2026-10-26)

Maintenance update. The code as printed in the book is tagged `first-edition`. The printed commands and stage functions keep working.

### Fixed
- **Baseline split.** The baseline was "the first 70% of rows", but the rows are sorted by pod name, so the baseline was the first 6 pods alphabetically and the 3 "affected pods" were the last 3. Baselines are now per pod, from the normal windows before the incident.
- **`--case`.** It changed the case label but loaded the default data.
- **Real data never used.** `download_data.py` unzipped LEMMA-RCA into a layout the pipeline doesn't read, so every run used the bundled files.
- **Pods dropped.** Pods missing from any one metric were dropped. On real data that removed the root-cause pod: storage IOPS covers 6 of 257 pods.
- **Windows.** Neighbouring windows shared a sample, and the configured `window_size` and `aggregation` were ignored.
- **Guardrails.**
  - `action_policies` (minimum confidence, actions that always need a human) were never applied.
  - The restart limit was never checked.
  - The rate limit counted only earlier runs.
- **LLM.** A failed call dropped the pod instead of falling back to the rules.
- **Act.**
  - Unseeded.
  - The duration printed differed from the logged end time.
  - `scale_up` could end with fewer replicas.
- **Deprecated `datetime.utcnow()`** (14 places).
- **Unsafe loading.** `np.load(allow_pickle=True)` on downloaded files could run code from a crafted file.

### Changed
- **Real LEMMA-RCA cases.**
  - `download_data.py` downloads a case at a pinned revision and verifies its SHA-256.
  - It range-reads only the log signals out of the 2.3 GB log zip.
  - It converts everything to 30-second resolution with a time axis.
  - It reads the fault label from the case README slides.
  - Output goes to `data/lemma-rca/<case>/`; run it with `python run_pipeline.py --case <case>`.
- **Loading.** Every `.npy` file goes through `pipeline/safe_npy.py`, which accepts data and NumPy arrays only.
- **Alignment.** Fuse aligns all modalities on the time axis and keeps every pod.
- **Incident from the KPI.** Plan finds when users were hurt (configurable threshold; LEMMA-RCA: error rate above 1%) and analyses the largest incident against each pod's own baseline.
- **Pod ranking.** Pods are ranked, and the top 10 are analysed.
- **Evaluation.** Observe scores the run against the fault label (root-cause rank, actions on it, KPI incident time against the labelled failure) and lists the most anomalous pods.
- **Separate reports.** Real-case reports go to `output/lemma-rca-<case>/`.
- **README.**
  - The bundled sample is labelled as synthetic.
  - The expected output is re-recorded for the sample and for cases 20240115 and 20240207.

### Added
- `pyproject.toml` and `uv.lock`; `requirements.txt` exported from the lock (Python ≥ 3.12; scikit-learn and requests removed, never imported).
- `tests/test_smoke.py` (10 tests), `make smoke`.
- CI on Python 3.12 and 3.13, including the printed commands and both LEMMA-RCA cases.

### Removed
- Committed `__pycache__/` files and `.DS_Store`.
