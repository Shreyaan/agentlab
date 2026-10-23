import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_generated_reference_is_up_to_date() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/gen_reference.py", "--check"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
