"""Build and package a patched upstream checkout on GitHub-hosted runners."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
OUT = ROOT / 'dist'
def run(*args, cwd=None, **kwargs):
    return subprocess.run(list(args), cwd=cwd or SRC, check=True, **kwargs)


def output(key, value):
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as f:
        f.write(f'{key}={value}\n')


def secret_group(names):
    present = [bool(os.environ.get(n)) for n in names]
    if any(present) and not all(present):
        raise RuntimeError('Incomplete secret group; missing: ' + ', '.join(n for n, p in zip(names, present) if not p))
    return all(present)


def property_value(value):
    # java.util.Properties reads ISO-8859-1 and interprets backslash escapes.
    value = value.replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
    value = value.replace('=', '\\=').replace(':', '\\:').replace(' ', '\\ ')
    units = value.encode('utf-16-be')
    return ''.join(chr(n) if 32 <= n < 127 else '\\u%04x' % n
                   for n in (int.from_bytes(units[i:i+2], 'big') for i in range(0, len(units), 2)))


def prepare():
    tag = os.environ['UPSTREAM_TAG']
    if not re.fullmatch(r'v\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?', tag):
        raise RuntimeError('Invalid upstream release tag')
    target = os.environ['TARGET']
    mode = os.environ.get('BUILD_TYPE', 'release')
    # Git for Windows may check out CRLF; patch context uses canonical LF.
    for p in [ROOT / 'noad.patch',
              SRC / 'app/shared/app-data/src/commonMain/kotlin/domain/episode/GetSubjectRecommendationFlowUseCase.kt',
              SRC / 'app/shared/ui-settings/src/commonMain/kotlin/ui/update/UpdateChecker.kt']:
        p.write_bytes(p.read_bytes().replace(b'\r\n', b'\n'))
    run('git', 'apply', '--check', str(ROOT / 'noad.patch'))
    run('git', 'apply', str(ROOT / 'noad.patch'))
    version = tag[1:]
    major, minor, patch = map(int, version.split('-')[0].split('.'))
    meta = 99
    if '-alpha' in version:
        meta = int(version.split('-alpha')[1])
    elif '-beta' in version:
        meta = 30 + int(version.split('-beta')[1])
    p = SRC / 'gradle.properties'
    text = p.read_text(encoding='utf-8')
    ios = target == 'ios'
    for key, value in {'version.name': version, 'package.version': version.split('-')[0],
                       'ios.version.code': f'{major}.{minor}.{patch * 100 + meta}',
                       'org.gradle.jvmargs': ('-Xmx12g -Dfile.encoding=UTF-8 '
                                              '-Dkotlin.daemon.jvm.options=-Xmx20g') if ios else '-Xmx4g -Dfile.encoding=UTF-8',
                       'kotlin.daemon.jvmargs': '-Xmx20g' if ios else '-Xmx3g',
                       'org.gradle.workers.max': '2',
                       'org.gradle.configuration-cache': 'false'}.items():
        pattern = '^' + re.escape(key) + '=.*$'
        if re.search(pattern, text, re.M):
            text = re.sub(pattern, lambda _: key + '=' + value, text, flags=re.M)
        else:
            text += '\n' + key + '=' + value + '\n'
    p.write_text(text, encoding='utf-8')
    props = {'ani.enable.firebase': 'false', 'ani.android.abis': 'all',
             'ani.android.debug.applicationIdSuffix': '.noad.debug'}
    if secret_group(['DANDANPLAY_APP_ID', 'DANDANPLAY_APP_SECRET']):
        props.update({
            'ani.dandanplay.app.id': os.environ['DANDANPLAY_APP_ID'],
            'ani.dandanplay.app.secret': os.environ['DANDANPLAY_APP_SECRET'],
        })
    else:
        print('::warning::DANDANPLAY_APP_ID and DANDANPLAY_APP_SECRET are not configured; Dandanplay danmaku will be unavailable.')
    if target == 'ios':
        props.update({'ani.enable.ios': 'true', 'ani.build.framework': 'true',
                      'kotlin.native.ignoreDisabledTargets': 'true'})
        bundle = os.environ.get('IOS_BUNDLE_ID', '').strip()
        if bundle:
            if not re.fullmatch(r'[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+', bundle):
                raise RuntimeError('Invalid IOS_BUNDLE_ID')
            for rel in ['app/ios/Animeko.xcodeproj/project.pbxproj',
                        'app/ios/Animeko/exportOptions.plist.template.txt']:
                f = SRC / rel
                f.write_text(f.read_text(encoding='utf-8').replace('org.animeko.animeko', bundle), encoding='utf-8')
            f = SRC / 'build-logic/src/main/kotlin/xcodeSigned.kt'
            original = f.read_text(encoding='utf-8')
            needle = r'org\.animeko\.animeko'
            if needle not in original:
                raise RuntimeError('Upstream iOS export template implementation changed')
            f.write_text(original.replace(needle, bundle.replace('.', r'\.')), encoding='utf-8')
    (SRC / 'local.properties').write_text(''.join(k + '=' + property_value(v) + '\n' for k, v in props.items()), encoding='ascii')
    (SRC / 'gradlew').chmod(0o755)
    OUT.mkdir(exist_ok=True)
    commit = run('git', 'rev-parse', 'HEAD', capture_output=True, text=True).stdout.strip()
    manifest = {'upstream_tag': tag, 'upstream_commit': commit, 'target': target,
                'build_type': mode, 'patch_sha256': hashlib.sha256((ROOT/'noad.patch').read_bytes()).hexdigest(),
                'workflow_commit': os.environ.get('GITHUB_SHA'),
                'ios_signed': False}
    (OUT / ('build-info-' + target + '.json')).write_text(json.dumps(manifest, indent=2) + '\n')
    run('git', 'diff', '--binary', '--output=' + str(OUT / ('source-changes-' + target + '.patch')))


def jbr():
    platform = os.environ['JBR_PLATFORM']
    if platform not in ['linux-x64', 'windows-x64', 'windows-aarch64', 'osx-x64', 'osx-aarch64']:
        raise RuntimeError('Unsupported JBR platform')
    name = f'jbrsdk_jcef-21.0.11-{platform}-b1163.116.tar.gz'
    url = 'https://cache-redirector.jetbrains.com/intellij-jbr/' + name
    archive = Path(os.environ['RUNNER_TEMP']) / name
    urllib.request.urlretrieve(url, archive)
    expected = urllib.request.urlopen(url + '.checksum').read().decode().split()[0].lower()
    actual = hashlib.sha512(archive.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError('JBR SHA-512 checksum mismatch')
    dest = Path(os.environ['RUNNER_TEMP']) / 'noad-jbr'
    dest.mkdir(exist_ok=True)
    run('tar', '-xzf', str(archive), '-C', str(dest), '--strip-components=1', cwd=ROOT)
    java_home = dest / 'Contents/Home' if platform.startswith('osx') else dest
    with open(os.environ['GITHUB_ENV'], 'a', encoding='utf-8') as f:
        f.write('JAVA_HOME=' + str(java_home) + '\n')
    with open(os.environ['GITHUB_PATH'], 'a', encoding='utf-8') as f:
        f.write(str(java_home / 'bin') + '\n')


def gradle(*tasks):
    wrapper = str(SRC / 'gradlew.bat') if os.name == 'nt' else './gradlew'
    run(wrapper, *tasks, '--stacktrace', '--no-configuration-cache', '--max-workers=2')


def gradle_retry(*tasks, attempts):
    for attempt in range(1, attempts + 1):
        try:
            gradle(*tasks)
            return
        except subprocess.CalledProcessError:
            if attempt == attempts:
                raise
            print(f'::warning::Gradle attempt {attempt}/{attempts} failed; retrying {", ".join(tasks)}')


def build():
    target = os.environ['TARGET']
    if target == 'android':
        mode = os.environ.get('BUILD_TYPE', 'release').capitalize()
        gradle(':app:android:assembleDefault' + mode, ':app:android:assembleTv' + mode)
    elif target == 'ios':
        gradle_retry(':app:ios:podInstall', attempts=2)
        gradle_retry(':app:ios:patchInfoPlist', attempts=2)
        gradle_retry(':app:ios:buildReleaseIpa', attempts=3)
    elif target == 'macos-aarch64':
        gradle(':app:desktop:packageReleaseDistributionForCurrentOS')
    else:
        gradle(':app:desktop:createReleaseDistributable')


def collect():
    target = os.environ['TARGET']
    version = os.environ['UPSTREAM_TAG'][1:]
    prefix = 'ani-' + version + '-noad'
    desktop = SRC / 'app/desktop/build/compose/binaries/main-release'
    if target == 'android':
        mode = os.environ.get('BUILD_TYPE', 'release')
        for flavor in ['default', 'tv']:
            folder = SRC / 'app/android/build/outputs/apk' / flavor / mode
            metadata = json.loads((folder / 'output-metadata.json').read_text(encoding='utf-8'))
            if len(metadata['elements']) != 4:
                raise RuntimeError('Expected universal APK and three ABI APKs')
            for item in metadata['elements']:
                abi = next((f['value'] for f in item['filters'] if f['filterType'] == 'ABI'), 'universal')
                p = folder / item['outputFile']
                name = prefix + ('-tv' if flavor == 'tv' else '') + '-' + mode + '-' + abi + '.apk'
                shutil.copy2(p, OUT / name)
    elif target == 'ios':
        shutil.copy2(SRC / 'app/ios/build/archives/release/Animeko.ipa',
                     OUT / (prefix + '-ios-unsigned.ipa'))
    elif target == 'macos-aarch64':
        files = list((desktop / 'dmg').glob('*.dmg'))
        if len(files) != 1:
            raise RuntimeError('Expected exactly one DMG')
        shutil.copy2(files[0], OUT / (prefix + '-' + target + '.dmg'))
    elif target == 'macos-x86_64':
        run('ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(desktop/'app/Ani.app'),
            str(OUT / (prefix + '-' + target + '.zip')))
    elif target.startswith('windows'):
        if not (desktop/'app/Ani/Ani.exe').is_file():
            raise RuntimeError('Missing Windows executable')
        shutil.make_archive(str(OUT/(prefix+'-'+target)), 'zip', desktop/'app', 'Ani')
    elif target == 'linux-x86_64':
        appdir = ROOT / 'AppDir'
        shutil.copytree(desktop/'app/Ani', appdir/'usr')
        for name in ['AppRun', 'animeko.desktop', 'icon.png']:
            shutil.copy2(SRC/'app/desktop/appResources/linux-x64'/name, appdir/name)
        (appdir/'AppRun').chmod(0o755)
        for rel in ['usr/bin/Ani', 'usr/lib/runtime/lib/jcef_helper', 'usr/lib/runtime/lib/cef_server']:
            if not os.access(appdir/rel, os.X_OK):
                raise RuntimeError('Missing executable permission: ' + rel)
        tool = ROOT/'appimagetool.AppImage'
        urllib.request.urlretrieve('https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage', tool)
        if hashlib.sha256(tool.read_bytes()).hexdigest() != 'ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0':
            raise RuntimeError('AppImage tool SHA-256 mismatch')
        tool.chmod(0o755)
        env = dict(os.environ, ARCH='x86_64', APPIMAGE_EXTRACT_AND_RUN='1')
        run(str(tool), str(appdir), str(OUT/(prefix+'-'+target+'.appimage')), cwd=ROOT, env=env)
    else:
        raise RuntimeError('Unknown target: ' + target)
    for p in list(OUT.iterdir()):
        if p.suffix != '.sha256':
            p.with_name(p.name+'.sha256').write_text(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n')


if __name__ == '__main__':
    {'prepare': prepare, 'jbr': jbr, 'build': build, 'collect': collect}[sys.argv[1]]()

