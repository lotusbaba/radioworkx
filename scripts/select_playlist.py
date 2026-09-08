"""Create a private, randomized ten-genre selection from catalog metadata."""
import json
import sys
from pathlib import Path
from app.policy import diverse_sample

pool=json.loads(Path(sys.argv[1] if len(sys.argv)>1 else 'catalog/bandcamp.json').read_text())
selection=diverse_sample(pool)
if len(selection)!=10:
    raise SystemExit('Need at least ten genres with different artists')
print(json.dumps(selection,indent=2))
