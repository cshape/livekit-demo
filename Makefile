.PHONY: install dev lint clean env

# One-time setup: Python deps, VAD/turn-detector weights, and web deps.
install:
	cd fish && uv sync
	cd fish && uv run python src/agent.py download-files
	cd web && pnpm install

# Bootstrap empty .env.local files from the examples. Won't clobber existing ones.
env:
	@test -f fish/.env.local || cp fish/.env.example fish/.env.local
	@test -f web/.env.local  || cp web/.env.example  web/.env.local
	@echo "Fill in fish/.env.local and web/.env.local with your keys."

# Run the agent worker + Next.js dev server side-by-side. Ctrl-C stops both.
dev:
	uvx honcho start

lint:
	cd fish && uv run ruff check src/ && uv run ruff format --check src/
	cd web  && pnpm exec tsc --noEmit

clean:
	rm -rf fish/.venv web/node_modules web/.next
