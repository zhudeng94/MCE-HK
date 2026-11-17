"""Optional code snapshot using the same .gitignore as the working project."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
def files():
    """Use this project's actual ignore rules, including in a pre-Git workspace."""
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory(prefix='cmhk-code-index-') as temporary:
        subprocess.run(['git', 'init', '-q', temporary], check=True)
        output = subprocess.check_output([
            'git', '--git-dir=' + str(Path(temporary)/'.git'), '--work-tree=' + str(ROOT),
            'ls-files', '--others', '--exclude-standard', '-z'], cwd=ROOT)
    return [ROOT / name.decode() for name in output.split(b'\0') if name]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    args=parser.parse_args()
    dest=args.destination.resolve()
    if dest == ROOT or ROOT in dest.parents and not str(dest.relative_to(ROOT)).startswith(('outputs/','.tmp/')):
        parser.error('Export to a new directory outside the project or under outputs/ or .tmp/')
    if dest.exists() and any(dest.iterdir()):
        parser.error('Destination must be empty; use a new directory for each export')
    selected=files()
    missing=[str(p.relative_to(ROOT)) for p in selected if not p.is_file()]
    if missing:
        parser.error(f'Missing required release files: {missing}')
    hashes={}
    for source in selected:
        name=str(source.relative_to(ROOT));target=dest/name
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        hashes[name]=hashlib.sha256(target.read_bytes()).hexdigest()
    (dest/'release_manifest.json').write_text(json.dumps({'scope':'calculation code, parameters, documentation and test fixtures; no production raw inputs or frontend', 'files_sha256':hashes},indent=2)+'\n')
    print(f'{len(hashes)} files exported to {dest}; no Git remote, commit or push was performed.')


if __name__=='__main__':main()
