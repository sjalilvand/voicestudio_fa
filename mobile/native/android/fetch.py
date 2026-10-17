#!/usr/bin/env python3
"""Fetch only pinned build inputs; no git mutations or model downloads."""
import hashlib
import json
import pathlib
import shutil
import tarfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
PINS = json.loads((ROOT.parent / 'pins.json').read_text())
CHECKSUMS = json.loads((ROOT / 'source-checksums.json').read_text())
BUILD = ROOT / 'build'

def fetch(name, url, digest):
    target = BUILD / 'downloads' / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_suffix('.partial')
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as output:
            shutil.copyfileobj(response, output)
        temporary.replace(target)
    with target.open('rb') as source:
        actual = hashlib.sha256()
        for block in iter(lambda: source.read(1024 * 1024), b''):
            actual.update(block)
    if actual.hexdigest() != digest:
        target.unlink()
        raise ValueError('SHA-256 mismatch: ' + name)
    return target

def extract(archive, destination):
    if destination.exists():
        return
    temporary = destination.with_name(destination.name + '.extract')
    shutil.rmtree(temporary, ignore_errors=True)
    temporary.mkdir(parents=True)
    with tarfile.open(archive) as source:
        # Reject path escapes and symlinks out of the source tree, including on
        # Python versions predating tarfile's data extraction filter.
        for member in source.getmembers():
            path = pathlib.PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Unsafe source archive path')
            if member.islnk() or member.issym():
                link = pathlib.PurePosixPath(member.linkname)
                if link.is_absolute() or '..' in link.parts:
                    raise ValueError('Unsafe source archive link')
        source.extractall(temporary)
    entries = list(temporary.iterdir())
    if len(entries) != 1:
        raise ValueError('Unexpected source archive layout')
    entries[0].rename(destination)
    temporary.rmdir()

if __name__ == '__main__':
    aar = PINS['sherpa-onnx']['android_aar']
    fetch('sherpa.aar', aar['url'], aar['sha256'])
    for name in ('omnivoice.cpp', 'llama.cpp'):
        pin = PINS[name]['source']
        checksum = CHECKSUMS[name]
        if pin['commit'] != checksum['commit']:
            raise ValueError('Update reviewed source checksum for ' + name)
        archive = fetch(name + '.tar.gz', pin['repo'].replace('https://github.com/', 'https://codeload.github.com/') + '/tar.gz/' + pin['commit'], checksum['sha256'])
        extract(archive, BUILD / 'sources' / (name + '-' + pin['commit']))
    ggml = CHECKSUMS['ggml']
    archive = fetch('ggml.tar.gz', 'https://codeload.github.com/' + ggml['repo'] + '/tar.gz/' + ggml['commit'], ggml['sha256'])
    destination = BUILD / 'sources' / ('omnivoice.cpp-' + PINS['omnivoice.cpp']['source']['commit']) / 'ggml'
    if destination.exists() and not list(destination.iterdir()):
        destination.rmdir()
    extract(archive, destination)

    # Source archives have no .git directory. Avoid accidentally stamping the
    # parent VoiceStudio checkout's identity into the runtime binary.
    version_script = BUILD / 'sources' / ('omnivoice.cpp-' + PINS['omnivoice.cpp']['source']['commit']) / 'tools/version.cmake'
    version_script.write_text('file(WRITE "${OUTPUT}" "#pragma once\\n#define OMNIVOICE_VERSION \\"' + PINS['omnivoice.cpp']['source']['commit'] + '\\"\\n")\n')
