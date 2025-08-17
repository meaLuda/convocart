# Variables
PYTHON = uv 
CONTAINER_NAME = orderbot
IMAGE_NAME = orderbot-image
PORT = 2056

# Tailwind CSS
tw_watch:
	@npx tailwindcss -i ./app/static/css/input.css -o ./app/static/css/output.css --watch

run_app:
	uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
	@echo "Starting application..."
	@echo "Visit http://localhost:8080 to access the application"
	@echo "Application running at http://localhost:$(PORT)"
# Docker Commands
build:
	docker build -t $(IMAGE_NAME) .

start:
	docker run -d --name $(CONTAINER_NAME) \
		-p $(PORT):$(PORT) \
		-v $(PWD):/src \
		--restart unless-stopped \
		$(IMAGE_NAME)
	@echo "Container started. Access at http://localhost:$(PORT)"

stop:
	docker stop $(CONTAINER_NAME)
	docker rm $(CONTAINER_NAME)

restart: stop start

shell:
	$(CONTAINER_NAME) /bin/bash

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

logs:
	docker logs -f $(CONTAINER_NAME)

# Alembic Migrations
alembic_init:
	$(PYTHON) -m alembic init alembic

alembic_revision:
	$(PYTHON) -m alembic revision --autogenerate -m "New migration"

alembic_upgrade:
	$(PYTHON) -m alembic upgrade head

alembic_downgrade:
	$(PYTHON) -m alembic downgrade -1

# Help
help:
	@echo "Available commands:"
	@echo "  make tw_watch          - Watch for Tailwind CSS changes"
	@echo "  make build             - Build Docker image"
	@echo "  make start             - Start container with volume mounting"
	@echo "  make stop              - Stop and remove the container"
	@echo "  make restart           - Restart the container (for code changes)"
	@echo "  make shell             - Enter container shell"
	@echo "  make fresh             - Complete rebuild (remove and recreate everything)"
	@echo "  make logs              - View container logs"
	@echo "  make alembic_init      - Initialize Alembic (run once)"
	@echo "  make alembic_revision  - Create a new migration"
	@echo "  make alembic_upgrade   - Apply all pending migrations"
	@echo "  make alembic_downgrade - Revert the last migration"

.PHONY: tw_watch build start stop restart shell fresh logs alembic_init alembic_revision alembic_upgrade alembic_downgrade help