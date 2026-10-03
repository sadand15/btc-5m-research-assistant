"""Build identity without copying .git or credential helpers into an image."""
import json
from pathlib import Path
import re
import sys
from btc5_v3.encoding import digest
from btc5_v3.prospective.identity import file_hash, identity

sha=sys.argv[1]
if not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError('explicit collector commit required')
root=Path('/app')
value=dict(collector_git_sha=sha,branch='v3-dev',
           collector_hash=digest({p.name:file_hash(p) for p in sorted((root/'src/btc5_v3/prospective').glob('*.py'))}))
(root/'collector-build.json').write_bytes(json.dumps(value,sort_keys=True).encode())
identity(root)
