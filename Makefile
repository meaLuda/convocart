tw_watch:
	@npx tailwindcss -i ./app/static/css/input.css -o ./app/static/css/output.css --watch

# Variables
CONTAINER_NAME = orderbot
IMAGE_NAME = orderbot-image
PORT = 8080

# Build Docker image
build:
	docker build -t $(IMAGE_NAME) .

# Start container with volume mounting for live code updates
start:
	docker run -d --name $(CONTAINER_NAME) \
		-p $(PORT):$(PORT) \
		-v $(PWD):/src \
		--restart unless-stopped \
		$(IMAGE_NAME)
	@echo "Container started. Access at http://localhost:$(PORT)"

# Stop the container
stop:
	docker stop $(CONTAINER_NAME)
	docker rm $(CONTAINER_NAME)

# Restart container (for config changes that need container restart)
restart: stop start

# Enter the container shell
shell:
	docker exec -it $(CONTAINER_NAME) /bin/bash

# Complete rebuild - remove everything and start fresh
fresh: 
	-docker stop $(CONTAINER_NAME)
	-docker rm $(CONTAINER_NAME)
	-docker rmi $(IMAGE_NAME)
	docker build -t $(IMAGE_NAME) .
	docker run -d --name $(CONTAINER_NAME) \
		-p $(PORT):$(PORT) \
		-v $(PWD):/src \
		--restart unless-stopped \
		$(IMAGE_NAME)
	@echo "Fresh container started. Access at http://localhost:$(PORT)"

# View logs
logs:
	docker logs -f $(CONTAINER_NAME)


# Help command
help:
	@echo "Available commands:"
	@echo "  make build         - Build Docker image"
	@echo "  make start         - Start container with volume mounting"
	@echo "  make stop          - Stop and remove the container"
	@echo "  make restart       - Restart the container (for code changes)"
	@echo "  make shell         - Enter container shell"
	@echo "  make fresh         - Complete rebuild (remove and recreate everything)"
	@echo "  make logs          - View container logs"

.PHONY: build start stop restart shell fresh logs help