.PHONY: setup smoke run data data-20240207 run-lemma run-20240207 clean

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

# Remove generated files: downloaded cases, their reports and the make run reports.
# The synthetic sample in data/20240115/ and the committed output/ files are kept.
clean:
	rm -rf data/lemma-rca output/lemma-rca-* output/make-run .pytest_cache
