.PHONY: test qe-up qe-down

test:
	python -m pytest

qe-up:
	docker compose -f compose.yaml -f compose.qe.yaml up --build -d --wait

qe-down:
	docker compose -f compose.yaml -f compose.qe.yaml down -v
