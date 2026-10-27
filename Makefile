.PHONY: smoke run data data-20240207 run-lemma run-20240207 clean

# Smoke tests on the bundled synthetic sample (no downloads)
smoke:
	uv run pytest -q

# The six stages on the bundled synthetic sample
run:
	uv run python run_pipeline.py

# LEMMA-RCA case 20240115 (193 MB download, 37 MB kept), then the pipeline on it
data:
	uv run python download_data.py --case 20240115

run-lemma: data
	uv run python run_pipeline.py --case 20240115

# A case without logs, whose root cause is not a pod
data-20240207:
	uv run python download_data.py --case 20240207

run-20240207: data-20240207
	uv run python run_pipeline.py --case 20240207

clean:
	rm -rf data/lemma-rca output/lemma-rca-* .pytest_cache
