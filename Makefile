# Variables
PYTHON = uv
CONTAINER_NAME = ConvoCart
IMAGE_NAME = ConvoCart-image
PORT = 2056

# Tailwind CSS
tw_watch:
	@npm run watch
tw_minify:
	@npm run build

run_app: 
	@echo "Starting FastAPI server..."
	@echo "Visit http://localhost:8080 to access the application"
	uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

run_celery:
	@echo "Starting Celery worker for cart recovery..."
	uv run celery -A app.services.cart_recovery_scheduler worker --loglevel=info

run_both: tw_minify
	@echo "Starting FastAPI and Celery worker..."
	@echo "Visit http://localhost:8080 to access the application"
	@echo "Press Ctrl+C to stop both services"
	@trap 'echo "Stopping services..."; pkill -f "uvicorn app.main"; pkill -f "celery.*cart_recovery_scheduler"; exit 0' INT TERM; \
	uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload & \
	uv run celery -A app.services.cart_recovery_scheduler worker --loglevel=info & \
	wait

stop_app:
	@echo "Stopping FastAPI and Celery services..."
	-pkill -f "uvicorn app.main"
	-pkill -f "celery.*cart_recovery_scheduler"
	@echo "Services stopped"

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

# Database & Migrations (PostgreSQL)
db_setup:
	@echo "Setting up PostgreSQL database..."
	@echo "Make sure DATABASE_URL is set in your .env file"
	uv run ./scripts/setup_postgresql.py

db_revision:
	$(PYTHON) run alembic revision --autogenerate -m "$(if $(m),$(m),New migration)"

db_upgrade:
	$(PYTHON) run alembic upgrade head

db_downgrade:
	$(PYTHON) run alembic downgrade -1

db_current:
	$(PYTHON) run alembic current

db_history:
	$(PYTHON) run alembic history

db_reset:
	@echo "⚠️  This will delete all migration files and reset the database schema!"
	@echo "Are you sure? (y/N): " && read answer && [ "$$answer" = "y" ]
	rm -rf alembic/versions/*.py
	@echo "Migration files deleted. Run 'make db_setup' to create fresh migrations."

# Development Commands
dev_install:
	uv sync
	@echo "Dependencies installed. Copy .env.example to .env and configure DATABASE_URL"

dev_check:
	@echo "Checking environment..."
	@if [ -f .env ]; then echo "✅ .env file exists"; else echo "❌ .env file missing - copy from .env.example"; fi
	@if grep -q "DATABASE_URL=" .env 2>/dev/null; then echo "✅ DATABASE_URL configured"; else echo "❌ DATABASE_URL not set in .env"; fi

# Help
help:
	@echo "Available commands:"
	@echo ""
	@echo "🚀 Development:"
	@echo "  make dev_install       - Install dependencies with uv"
	@echo "  make dev_check         - Check environment configuration"
	@echo "  make run_app           - Start the application"
	@echo ""
	@echo "🗄️  Database (PostgreSQL):"
	@echo "  make db_setup          - Set up PostgreSQL database (interactive)"
	@echo "  make db_revision m='message' - Create new migration"
	@echo "  make db_upgrade        - Apply all pending migrations"
	@echo "  make db_downgrade      - Revert the last migration"
	@echo "  make db_current        - Show current migration"
	@echo "  make db_history        - Show migration history"
	@echo "  make db_reset          - Reset all migrations (⚠️  destructive)"
	@echo ""
	@echo "🎨 Frontend:"
	@echo "  make tw_watch          - Watch for Tailwind CSS changes"
	@echo "  make tw_minify         - Build minified CSS"
	@echo ""
	@echo "🐳 Docker:"
	@echo "  make build             - Build Docker image"
	@echo "  make start             - Start container"
	@echo "  make stop              - Stop and remove container"
	@echo "  make restart           - Restart container"
	@echo "  make fresh             - Complete rebuild"
	@echo "  make logs              - View container logs"

.PHONY: tw_watch tw_minify run_app build start stop restart shell fresh logs dev_install dev_check db_setup db_revision db_upgrade db_downgrade db_current db_history db_reset help