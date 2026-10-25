"""Create the standard Android scaffold with the pinned Flutter SDK; apply app-owned files."""
from pathlib import Path
import os,shutil,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
if not (root/'android').exists():
    with tempfile.TemporaryDirectory(prefix='nantuan-scaffold-') as tmp:
        generated=Path(tmp)/'nantuan_club'
        subprocess.run(['flutter','create','--platforms=android','--org','org.nantuan','--project-name','nantuan_club','--empty',str(generated)],check=True)
        shutil.copytree(generated/'android',root/'android')
android=root/'android'
for source,target in [('MainActivity.kt','app/src/main/kotlin/org/nantuan/nantuan_club/MainActivity.kt'),('AndroidManifest.xml','app/src/main/AndroidManifest.xml'),('app_icon.xml','app/src/main/res/drawable/app_icon.xml')]:
    dest=android/target;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/'overlays'/source,dest)
# Cleartext is allowed only in the disposable debug emulator build, never release.
p=android/'app/src/debug/AndroidManifest.xml'
p.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application android:usesCleartextTraffic="true" /></manifest>\n',encoding='utf-8')
p=android/'app/build.gradle.kts';s=p.read_text(encoding='utf-8')
s=s.replace('minSdk = flutter.minSdkVersion','minSdk = 24')
# A main-only release workflow supplies the persistent private signing key.
if 'create("clubRelease")' not in s:s=s.replace('    buildTypes {','''    signingConfigs {
        create("clubRelease") {
            storeFile = System.getenv("ANDROID_KEYSTORE_PATH")?.let { file(it) }
            storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
            keyAlias = "nantuan"
            keyPassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
        }
    }
    buildTypes {''')
s=s.replace('signingConfig = signingConfigs.getByName("debug")','signingConfig = if (System.getenv("ANDROID_KEYSTORE_PATH") != null) signingConfigs.getByName("clubRelease") else signingConfigs.getByName("debug")')
p.write_text(s,encoding='utf-8')
