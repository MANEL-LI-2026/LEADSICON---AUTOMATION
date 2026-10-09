"""Prepare the files to upload to the protected HF endpoint's model repository."""
import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
ENDPOINT_FILES = ('handler.py', 'alignment.py', 'remote_processor.py', 'requirements.txt', 'README.md')
BACKEND_FILES = ('library_store.py', 'library_worker.py', 'drive_client.py', 'transcription.py',
                 'hf_transcription.py', 'transcript_validation.py', 'kie.py', 'scraper.py', 'ad_inputs.py')


def build(output):
    output = Path(output).resolve()
    sources = [ROOT / 'integrations/huggingface' / name for name in ENDPOINT_FILES] + [ROOT / name for name in BACKEND_FILES]
    if output == ROOT or output.is_relative_to(ROOT):
        raise ValueError('Choose an output directory outside the checkout to preserve repository files.')
    output.mkdir(parents=True, exist_ok=True)
    for source in sources:
        destination = output / source.name
        if destination.exists():
            raise ValueError('Use a new empty output directory; no existing files are overwritten.')
    for source in sources:
        shutil.copyfile(source, output / source.name)
    return len(sources)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(str(build(args.output)) + ' source files prepared. No credentials copied or resources deployed.')
