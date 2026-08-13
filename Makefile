.PHONY: test qe-up qe-down

test:
	python -m pytest

qe-up:
	docker compose up --build -d --wait

qe-down:
	docker compose down -v
