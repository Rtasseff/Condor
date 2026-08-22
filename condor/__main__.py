"""`python -m condor` entry point."""
import sys

from .cli import main

sys.exit(main())
