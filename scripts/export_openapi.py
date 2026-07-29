"""OpenAPI semasini dosyaya yazar.

Frontend'in tipli istemcisi bu semadan uretilir; boylece API sozlesmesi tek
kaynaktan gelir ve sinirda elle tip yazilmaz. Sunucuyu ayaga kaldirmaya gerek
yok -- uygulama nesnesinden dogrudan uretiliyor.

Kullanim:
    python scripts/export_openapi.py                    # openapi.json
    python scripts/export_openapi.py ../frontend/openapi.json

Ardindan frontend tarafinda:
    npx openapi-typescript openapi.json -o src/lib/api-types.ts
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import create_app


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
    schema = create_app().openapi()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")

    paths = len(schema.get("paths", {}))
    models = len(schema.get("components", {}).get("schemas", {}))
    print(f"{target}  ·  {paths} uc  ·  {models} model")
    print("Frontend: npx openapi-typescript openapi.json -o src/lib/api-types.ts")


if __name__ == "__main__":
    main()
