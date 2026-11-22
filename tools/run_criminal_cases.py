"""Criminal Law cases: the same DDL driver as run_cases.py, with the criminal rules and cases.
  python tools/run_criminal_cases.py            # all 30 scenarios
  python tools/run_criminal_cases.py rob-1 -v   # one scenario with its derivation"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import crim_rules as CR  # noqa: E402
import run_cases as RC  # noqa: E402
from paths import ROOT  # noqa: E402

RC.RULES = {r['key']: r for _, rs in CR.MODULES.values() for r in rs}
RC.FR = CR

if __name__ == '__main__':
    sys.exit(RC.main(ROOT / 'reasoning' / 'cases' / 'criminal.json', ROOT / 'reasoning' / 'criminal_rules.lp'))
