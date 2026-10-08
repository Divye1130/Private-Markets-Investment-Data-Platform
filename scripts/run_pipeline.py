from pathlib import Path
import json
import sys

ROOT_IMPORT = Path(__file__).resolve().parents[1]
if str(ROOT_IMPORT) not in sys.path:
    sys.path.insert(0, str(ROOT_IMPORT))

from src.generate_data import generate_dataset
from src.pipeline import run_pipeline

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    generation = generate_dataset(ROOT)
    summary = run_pipeline(ROOT)
    print(json.dumps({"generation": generation, "pipeline": summary}, indent=2))
