"""Explicit one-time download; inference never contacts the model hub."""
import hashlib
import json
from pathlib import Path
import urllib.request

REPOSITORY = 'cklxx/laya-browser'
REVISION = '645cf366a2ae35f1086e8c20eff48f909bb49206'
FILES = ('rl_agent_config.json', 'encoder/config.json', 'model.safetensors',
         'tokenizer/tokenizer.json', 'tokenizer/tokenizer_config.json')
DEFAULT_PATH = Path('.models/laya-browser') / REVISION


def download(destination=DEFAULT_PATH):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {'repository': REPOSITORY, 'revision': REVISION, 'sha256': {}}
    for name in FILES:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + '.partial')
        digest = hashlib.sha256()
        print('Downloading', name, flush=True)
        with urllib.request.urlopen(f'https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}', timeout=120) as response, temporary.open('wb') as output:
            while block := response.read(1024 * 1024):
                digest.update(block)
                output.write(block)
        temporary.replace(target)
        manifest['sha256'][name] = digest.hexdigest()
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print('Local checkpoint:', destination.resolve())


if __name__ == '__main__':
    download()
