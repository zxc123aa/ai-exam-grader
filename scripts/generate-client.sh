#! /usr/bin/env bash

set -e
set -x

cd backend
if command -v uv >/dev/null 2>&1; then
  uv run python -c "import app.main; import json; print(json.dumps(app.main.app.openapi()))" > ../openapi.json
else
  python3 -c "import app.main; import json; print(json.dumps(app.main.app.openapi()))" > ../openapi.json
fi
cd ..
mv openapi.json frontend/
if command -v bun >/dev/null 2>&1; then
  bun run --filter frontend generate-client
  bun run lint
else
  npm run --workspace frontend generate-client
  npm run --workspace frontend lint
fi
