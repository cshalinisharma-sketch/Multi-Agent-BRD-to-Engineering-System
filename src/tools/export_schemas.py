"""Export every agent output contract as JSON Schema to docs/schemas/."""
import json

from ..config import ROOT
from ..contracts import AGENT_OUTPUT_MODELS, ParsedBRD


def main():
    out = ROOT / "docs" / "schemas"
    out.mkdir(parents=True, exist_ok=True)
    for name, model in {**AGENT_OUTPUT_MODELS, "brd_parser": ParsedBRD}.items():
        (out / f"{name}.schema.json").write_text(json.dumps(model.model_json_schema(), indent=2))
    print(f"wrote {len(AGENT_OUTPUT_MODELS) + 1} schemas to {out}")


if __name__ == "__main__":
    main()
