.PHONY: build build-router build-worker deploy deploy-router deploy-worker clean test migrate migrate-new

ROUTER_FUNCTION := spend-tracking-router
WORKER_FUNCTION := spend-tracking-worker
BUILD_DIR := .build
AWS_REGION := us-east-1

build: build-router build-worker

build-router:
	rm -rf $(BUILD_DIR)/router
	mkdir -p $(BUILD_DIR)/router
	pip install --no-deps -t $(BUILD_DIR)/router/ --quiet --platform manylinux2014_x86_64 --python-version 3.12 --only-binary=:all: psycopg2-binary
	cp -r src/spend_tracking $(BUILD_DIR)/router/
	cd $(BUILD_DIR)/router && zip -r ../router.zip . -x "*.pyc" "__pycache__/*"

build-worker:
	rm -rf $(BUILD_DIR)/worker
	mkdir -p $(BUILD_DIR)/worker
	pip install --no-deps -t $(BUILD_DIR)/worker/ --quiet --platform manylinux2014_x86_64 --python-version 3.12 --only-binary=:all: psycopg2-binary
	cp -r src/spend_tracking $(BUILD_DIR)/worker/
	cd $(BUILD_DIR)/worker && zip -r ../worker.zip . -x "*.pyc" "__pycache__/*"

deploy-router: build-router
	aws lambda update-function-code \
		--function-name $(ROUTER_FUNCTION) \
		--zip-file fileb://$(BUILD_DIR)/router.zip \
		--region $(AWS_REGION)

deploy-worker: build-worker
	aws lambda update-function-code \
		--function-name $(WORKER_FUNCTION) \
		--zip-file fileb://$(BUILD_DIR)/worker.zip \
		--region $(AWS_REGION)

deploy: deploy-router deploy-worker

clean:
	rm -rf $(BUILD_DIR)

test:
	poetry run pytest tests/ -v

migrate:
	poetry run alembic upgrade head

migrate-new:
	poetry run alembic revision -m "$(name)"
