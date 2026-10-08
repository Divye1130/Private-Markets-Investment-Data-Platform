.PHONY: setup run test dashboard clean
setup:
	python -m pip install -r requirements.txt
run:
	python scripts/run_pipeline.py
	python scripts/build_dashboard.py
test:
	pytest -q
dashboard:
	python scripts/build_dashboard.py
clean:
	rm -f warehouse/private_markets.db
	rm -f data/raw/*.csv data/raw/*.json data/processed/*.csv data/quarantine/*.csv data/documents/*.pdf
