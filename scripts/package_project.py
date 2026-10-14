"""Упаковка разрешённых исходников; окружения, секреты и веса не включаются."""
import hashlib
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
DIRECTORIES=['app','static','data','tests','scripts','evaluation','docs']
FILES=['README.md','requirements.txt','requirements-lock.txt','run.bat','.gitignore']
SUFFIXES={'.py','.html','.css','.js','.json','.md','.txt','.png','.jpg','.svg'}


def allowed(path):
    relative=path.relative_to(ROOT)
    if any(part in {'.venv','__pycache__','.git','.codex','.agents','node_modules','weights','models','artifacts'} for part in relative.parts):return False
    if path.suffix.lower() not in SUFFIXES:return False
    if path.name.startswith('.env') or any(term in path.name.lower() for term in ['secret','credential','token','private_key']):return False
    if relative.parts[:2]==('evaluation','results') and path.name not in {'status.json','comparison.md'}:return False
    return True


def main():
    output=ROOT/'dist'/'garden-planner-e61.zip';output.parent.mkdir(exist_ok=True)
    paths=[]
    for folder in DIRECTORIES:
        paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and allowed(p))
    paths.extend(ROOT/f for f in FILES if (ROOT/f).is_file())
    manifest={}
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(paths)):
            data=path.read_bytes();name=path.relative_to(ROOT).as_posix();archive.writestr(name,data);manifest[name]=hashlib.sha256(data).hexdigest()
        archive.writestr('MANIFEST.sha256','\n'.join(digest+'  '+name for name,digest in manifest.items())+'\n')
    print(f'Created {output.name}: {len(manifest)} files, {output.stat().st_size} bytes.')
    print('Virtual environment, model weights, original assignment DOCX and raw AI runs were not included.')


if __name__=='__main__':main()
