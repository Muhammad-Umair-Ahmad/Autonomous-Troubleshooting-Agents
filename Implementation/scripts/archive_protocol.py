"""Preserve a reproducible source/input bundle for the frozen study, without models/secrets."""
import tarfile
from neta.util import ROOT,read,write,digest,now


def archive_protocol(manifest):
    expected=digest({k:v for k,v in manifest.items() if k!='manifest_hash'})
    if expected!=manifest['manifest_hash']:raise RuntimeError('Manifest integrity mismatch')
    source={str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in sorted((ROOT/'src/neta').rglob('*.py'))}
    if digest(source)!=manifest['code_hash']:raise RuntimeError('Cannot archive changed study implementation')
    folder=ROOT/'results/protocols'/manifest['manifest_hash']
    folder.mkdir(parents=True,exist_ok=True)
    destination=folder/'source-and-inputs.tar.gz'
    metadata=folder/'bundle.json'
    if destination.exists():
        saved=read(metadata)
        if saved['archive_sha256']!=digest(destination.read_bytes()):raise RuntimeError('Archived study bundle changed')
        return saved
    files=list((ROOT/'src/neta').rglob('*.py'))+list((ROOT/'scripts').glob('*.py'))+list((ROOT/'scripts').glob('*.sh'))
    files+=[ROOT/'scripts/neta',ROOT/'README.md',ROOT/'pyproject.toml',ROOT/'requirements-lock.txt',
            ROOT/'docs/METHODOLOGY.md',ROOT/'configs/experiments.main.json',ROOT/'configs/sources.lock.json',
            ROOT/'configs/experiment-plan.json',ROOT/'data/public/local-cases.json',ROOT/'data/private/local-truth.json',
            ROOT/'data/dataset-freeze.json',ROOT/'knowledge/snapshots/docs-v1.json',ROOT/'knowledge/snapshots/curated-v1.json']
    files+=list((ROOT/'deploy').glob('Dockerfile*'))
    files+=list((ROOT/'labs/base').rglob('*'))+list((ROOT/'tests').glob('*.py'))
    files+=[ROOT/'configs/models.yaml',ROOT/'configs/environment.lock.json',ROOT/'configs/reference-documents.json']
    files=sorted(set(p for p in files if p.is_file()))
    temporary=destination.with_suffix('.tmp')
    with tarfile.open(temporary,'w:gz') as archive:
        for path in files:archive.add(path,arcname=str(path.relative_to(ROOT)),recursive=False)
    temporary.replace(destination)
    saved={'created':now(),'manifest_hash':manifest['manifest_hash'],'archive_sha256':digest(destination.read_bytes()),
           'files':{str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in files},
           'note':'Contains evaluator-only synthetic fault labels; never mount this bundle into an agent sandbox. Model/container binaries are identified by the frozen manifest, not copied here.'}
    write(metadata,saved)
    return saved
