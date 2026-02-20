.PHONY: build build-router build-worker deploy deploy-router deploy-worker clean test

ROUTER_FUNCTION := spend-tracking-router
WORKER_FUNCTION := spend-tracking-worker
BUILD_DIR := .build

build: build-router build-worker

build-router:
	rm -rf $(BUILD_DIR)/router
	mkdir -p $(BUILD_DIR)/router
	poetry export --without-hashes --without dev -o $(BUILD_DIR)/router/requirements.txt
	pip install -r $(BUILD_DIR)/router/requirements.txt -t $(BUILD_DIR)/router/ --quiet
	cp -r src/spend_tracking $(BUILD_DIR)/router/
	cd $(BUILD_DIR)/router && zip -r ../router.zip . -x "*.pyc" "__pycache__/*"

build-worker:
	rm -rf $(BUILD_DIR)/worker
	mkdir -p $(BUILD_DIR)/worker
	poetry export --without-hashes --without dev -o $(BUILD_DIR)/worker/requirements.txt
	pip install -r $(BUILD_DIR)/worker/requirements.txt -t $(BUILD_DIR)/worker/ --quiet
	cp -r src/spend_tracking $(BUILD_DIR)/worker/
	cd $(BUILD_DIR)/worker && zip -r ../worker.zip . -x "*.pyc" "__pycache__/*"

deploy-router: build-router
	aws lambda update-function-code \
		--function-name $(ROUTER_FUNCTION) \
		--zip-file fileb://$(BUILD_DIR)/router.zip

deploy-worker: build-worker
	aws lambda update-function-code \
		--function-name $(WORKER_FUNCTION) \
		--zip-file fileb://$(BUILD_DIR)/worker.zip

deploy: deploy-router deploy-worker

clean:
	rm -rf $(BUILD_DIR)

test:
	poetry run pytest tests/ -v
