"""File locations of the release."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LRML_FULL = ROOT / 'resources' / 'civil' / 'civil_graph.lrml'
LRML_RULES = LRML_FULL
RULES_LP = ROOT / 'reasoning' / 'civil_rules.lp'
CASES = ROOT / 'reasoning' / 'cases' / 'civil.json'
ENGINE = ROOT / 'engine' / 'ddl_engine'          # fetched by engine/fetch_ddl.sh
