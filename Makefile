.PHONY: up down reset seed logs test backend-test frontend-test e2e dev-db

up:            ## build and start everything in Docker  ->  http://localhost:8080
	docker compose up --build -d
	@echo "Web: http://localhost:8080   API docs: http://localhost:8080/api/docs   (make seed for demo data)"

down:          ## stop containers (keeps data)
	docker compose down

reset:         ## stop and DELETE database + report files
	docker compose down -v

seed:          ## load demo company (priya@northwind.dev / Demo@12345)
	docker compose --profile demo run --rm seed

logs:          ## follow API + worker logs (verification / report emails are printed here in dev)
	docker compose logs -f api worker

test: backend-test frontend-test

backend-test:  ## needs PostgreSQL on localhost:5432 (user postgres/postgres), see README
	cd backend && pytest

frontend-test:
	cd frontend && npm test && npm run typecheck

e2e:           ## browser tour against http://localhost:8080 (start the stack with AUTH_RATE_LIMIT_PER_MIN=0 make up, then make seed)
	cd e2e && npm install && npx playwright install chromium && BASE_URL=http://localhost:8080 PG_URL=postgresql://rs_owner:rs_owner@localhost:5433/reporting node ui.cjs
