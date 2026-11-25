.PHONY: setup smoke run data data-20240207 run-lemma run-20240207 explain check-data load try-anomaly-threshold try-window-size try-auto-approve clean

# A bare `make` runs the smoke test, as it did before the uniform targets were added.
.DEFAULT_GOAL := smoke

# Uniform targets for The Playbooks. The book's commands (pip install -r requirements.txt,
# python download_data.py --case 20240115, python run_pipeline.py) still work as printed.
# python run_pipeline.py still writes its reports to output/.

# Install the locked dependencies into .venv. The synthetic sample is in the repository.
setup:
	uv sync --frozen

# Smoke tests on the bundled synthetic sample (no downloads)
smoke:
	uv run --frozen pytest -q

# The six stages on the bundled synthetic sample. The reports go to output/make-run/
# (gitignored), so the committed output/ files are left as they are.
run: setup
	uv run --frozen python run_pipeline.py --output-dir output/make-run/
	@echo "playbook-12-multimodal-streamkit-ops-pipeline" > .playbook-done

# LEMMA-RCA case 20240115 (193 MB download, 37 MB kept), then the pipeline on it
data:
	uv run --frozen python download_data.py --case 20240115

run-lemma: data
	uv run --frozen python run_pipeline.py --case 20240115

# A case without logs, whose root cause is not a pod
data-20240207:
	uv run --frozen python download_data.py --case 20240207

run-20240207: data-20240207
	uv run --frozen python run_pipeline.py --case 20240207

# Why does a pod rank where it does? make explain POD=gateway-stu901 [CASE=20240115]
explain: setup
	@test -n "$(POD)" || { echo "Usage: make explain POD=pod-name [CASE=20240115]"; exit 2; }
	@uv run --frozen python scripts/explain_pod.py --pod "$(POD)" $(if $(CASE),--case "$(CASE)")

# Your own cluster: metrics.csv, kpi.csv and optional logs.csv and fault_label.json in DIR
# (see README, "Use your own data"). check-data checks every file and writes nothing; load converts
# the folder to data/lemma-rca/own-<name>/ and runs the pipeline on it.
#   make check-data DIR=my_cluster
#   make load DIR=my_cluster
check-data: setup
	@test -n "$(DIR)" || { echo "Usage: make check-data DIR=path/to/folder"; exit 2; }
	@uv run --frozen python scripts/own_cluster.py --dir "$(DIR)" --check-only

load: setup
	@test -n "$(DIR)" || { echo "Usage: make load DIR=path/to/folder"; exit 2; }
	@uv run --frozen python scripts/own_cluster.py --dir "$(DIR)"

# Try this: three measured experiments (see README, "Try this"), rule-based, nothing written.
# On the bundled sample; CASE=20240115 runs a downloaded case (make data first).
try-anomaly-threshold: setup
	@uv run --frozen python experiments/anomaly_threshold.py

try-window-size: setup
	@uv run --frozen python experiments/window_size.py

try-auto-approve: setup
	@uv run --frozen python experiments/auto_approve.py

# Remove generated files: downloaded cases, their reports and the make run reports.
# The synthetic sample in data/20240115/ and the committed output/ files are kept.
# Converted own data (data/lemma-rca/own-*) and its reports (output/lemma-rca-own-*) go too.
clean:
	rm -rf data/lemma-rca output/lemma-rca-* output/make-run .pytest_cache
