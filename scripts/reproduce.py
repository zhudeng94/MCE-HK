"""Reproduce core emissions from cached inputs; comparisons are optional."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cmhk.cli import main

if __name__ == '__main__':
    args = sys.argv[1:]
    # Legacy --skip-comparisons now agrees with the default core-only workflow.
    args = [arg for arg in args if arg != '--skip-comparisons']
    main(['run', *args])
