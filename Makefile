.PHONY: build deploy deploy-email-router deploy-email-worker deploy-line-webhook-router deploy-line-message-worker clean test migrate migrate-new lint lint-fix format-check format typecheck ci

ROUTER_FUNCTION := spend-tracking-router
WORKER_FUNCTION := spend-tracking-worker
LINE_WEBHOOK_ROUTER_FUNCTION := spend-tracking-line-webhook-router
LINE_MESSAGE_WORKER_FUNCTION := spend-tracking-line-message-worker
BUILD_DIR := .build
AWS_REGION := us-east-1

build:
	rm -rf $(BUILD_DIR)/lambda $(BUILD_DIR)/lambda.zip
	mkdir -p $(BUILD_DIR)/lambda
	pip install --no-deps -t $(BUILD_DIR)/lambda/ --quiet --platform manylinux2014_x86_64 --python-version 3.12 --only-binary=:all: psycopg2-binary
	pip install -t $(BUILD_DIR)/lambda/ --quiet anthropic
	cp -r src/spend_tracking $(BUILD_DIR)/lambda/
	find $(BUILD_DIR)/lambda -name '*_test.py' -delete
	cd $(BUILD_DIR)/lambda && zip -r ../lambda.zip . -x "*.pyc" "__pycache__/*"

deploy-email-router: build
	aws lambda update-function-code \
		--function-name $(ROUTER_FUNCTION) \
		--zip-file fileb://$(BUILD_DIR)/lambda.zip \
		--region $(AWS_REGION)

deploy-email-worker: build
	aws lambda update-function-code \
		--function-name $(WORKER_FUNCTION) \
		--zip-file fileb://$(BUILD_DIR)/lambda.zip \
		--region $(AWS_REGION)

deploy-line-webhook-router: build
	aws lambda update-function-code \
		--function-name $(LINE_WEBHOOK_ROUTER_FUNCTION) \
		--zip-file fileb://$(BUILD_DIR)/lambda.zip \
		--region $(AWS_REGION)

deploy-line-message-worker: build
	aws lambda update-function-code \
		--function-name $(LINE_MESSAGE_WORKER_FUNCTION) \
		--zip-file fileb://$(BUILD_DIR)/lambda.zip \
		--region $(AWS_REGION)

deploy: deploy-email-router deploy-email-worker deploy-line-webhook-router deploy-line-message-worker

clean:
	rm -rf $(BUILD_DIR)

test:
	PYTHONPATH=src poetry run pytest src/ -v

migrate:
	poetry run alembic upgrade head

migrate-new:
	poetry run alembic revision -m "$(name)"

lint:
	poetry run ruff check src/

lint-fix:
	poetry run ruff check --fix src/

format-check:
	poetry run ruff format --check src/

format:
	poetry run ruff format src/

typecheck:
	PYTHONPATH=src poetry run mypy

ci: lint format-check typecheck test build
