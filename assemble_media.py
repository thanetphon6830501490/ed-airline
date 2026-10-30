"""Restore a large video from upload-sized parts before deployment."""
from pathlib import Path
import hashlib
import json


def assemble(root=None):
    root = Path(root or Path(__file__).parent).resolve()
    for item in json.loads((root / 'media-parts/manifest.json').read_text(encoding='utf8')):
        target = (root / item['target']).resolve()
        if root not in target.parents:
            raise ValueError('Media target must remain inside the project')
        content = b''.join((root / 'media-parts' / part).read_bytes() for part in item['parts'])
        if hashlib.sha256(content).hexdigest() != item['sha256']:
            raise ValueError('Video parts failed integrity verification')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        print('Restored media:', item['target'])


if __name__ == '__main__':
    assemble()
