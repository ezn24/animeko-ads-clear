"""Offline checks for signing validation and artifact collection."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('build', Path(__file__).with_name('build.py'))
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class BuildTests(unittest.TestCase):
    def test_partial_secret_group_reports_names_only(self):
        with patch.dict(os.environ, {'KEY': 'private-value'}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'missing: PASSWORD') as error:
                build.secret_group(['KEY', 'PASSWORD'])
            self.assertNotIn('private-value', str(error.exception))

    def test_property_escape(self):
        self.assertEqual(build.property_value(' C:\\test\na=b:測試'),
                         r'\ C\:\\test\na\=b\:\u6e2c\u8a66')
        self.assertEqual(build.property_value('é'), r'\u00e9')

    def test_gradle_retry_recovers_from_transient_failure(self):
        failure = build.subprocess.CalledProcessError(1, ['./gradlew', ':task'])
        with patch.object(build, 'gradle', side_effect=[failure, None]) as gradle:
            build.gradle_retry(':task', attempts=2)
        self.assertEqual(gradle.call_count, 2)

    def test_android_collection_preserves_flavor_and_abi(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            out = root / 'dist'
            out.mkdir()
            for flavor in ['default', 'tv']:
                folder = root / 'src/app/android/build/outputs/apk' / flavor / 'release'
                folder.mkdir(parents=True)
                elements = []
                for abi in ['arm64-v8a', 'armeabi-v7a', 'x86_64', 'universal']:
                    filename = abi + '.apk'
                    (folder / filename).write_bytes((flavor + abi).encode())
                    filters = [] if abi == 'universal' else [{'filterType': 'ABI', 'value': abi}]
                    elements.append({'outputFile': filename, 'filters': filters})
                (folder / 'output-metadata.json').write_text(json.dumps({'elements': elements}))
            with patch.object(build, 'SRC', root/'src'), patch.object(build, 'OUT', out), \
                    patch.dict(os.environ, {'TARGET': 'android', 'BUILD_TYPE': 'release', 'UPSTREAM_TAG': 'v6.2.0'}):
                build.collect()
            self.assertEqual(len(list(out.glob('*.apk'))), 8)
            self.assertEqual(len(list(out.glob('*.sha256'))), 8)
            self.assertEqual((out/'ani-6.2.0-noad-tv-release-universal.apk').read_bytes(), b'tvuniversal')
            self.assertEqual((out/'ani-6.2.0-noad-release-arm64-v8a.apk').read_bytes(), b'defaultarm64-v8a')

    def test_android_incomplete_abis_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root/'src/app/android/build/outputs/apk/default/release'
            folder.mkdir(parents=True)
            (folder/'output-metadata.json').write_text('{"elements": []}')
            with patch.object(build, 'SRC', root/'src'), patch.object(build, 'OUT', root/'dist'), \
                    patch.dict(os.environ, {'TARGET': 'android', 'BUILD_TYPE': 'release', 'UPSTREAM_TAG': 'v6.2.0'}):
                with self.assertRaisesRegex(RuntimeError, 'Expected universal APK'):
                    build.collect()


if __name__ == '__main__':
    unittest.main()

