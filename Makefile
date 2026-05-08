.PHONY: help install run build docker-up docker-down

help:
	@echo "Antigravity AI Platform Commands:"
	@echo "  install      - Install dependencies"
	@echo "  run          - Run backend and frontend locally"
	@echo "  build        - Build frontend"
	@echo "  docker-up    - Start services with Docker Compose"
	@echo "  docker-down  - Stop Docker services"

install:
	pip install -r requirements.txt
	cd frontend && npm install

run:
	@echo "Starting backend..."
	uvicorn backend.main:app --reload &
	@echo "Starting frontend..."
	cd frontend && npm run dev

build:
	cd frontend && npm run build

docker-up:
	docker-compose up --build

docker-down:
	docker-compose down
