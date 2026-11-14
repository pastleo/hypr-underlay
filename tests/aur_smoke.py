"""Build the Arch package recipe against a public-files-only local Git fixture.

Does not install packages, modify the main Git index, contact GitHub, or submit
to AUR. Requires Arch makepkg/base-devel and the recipe's dependencies.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import re

ROOT = Path(__file__).resolve().parents[1]


def run(args, cwd, **kwargs):
    return subprocess.run(args, cwd=cwd, check=True, **kwargs)


def main():
    output = ROOT / "build"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="underlay-aur-", dir=os.environ.get("HYPR_UNDERLAY_TEST_TMPDIR")) as directory:
        work = Path(directory)
        upstream = work / "upstream.git"
        upstream.mkdir()
        files = subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
        ).split(b"\0")
        for raw in files:
            if not raw:
                continue
            relative = Path(os.fsdecode(raw))
            if not (ROOT / relative).is_file():
                continue  # Ignore tracked deletions in a development checkout.
            if relative.name == "AGENTS.local.md" or relative.parts[0] in (".git", "build"):
                raise RuntimeError("Private/build files entered the public source list")
            destination = upstream / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
        run(["git", "init", "-q"], upstream)
        run(["git", "add", "."], upstream)
        run(["git", "-c", "user.name=Packaging test", "-c", "user.email=test@example.invalid",
             "-c", "commit.gpgsign=false", "commit", "-qm", "Local packaging fixture"], upstream)
        recipe = work / "recipe"
        shutil.copytree(ROOT / "packaging/aur", recipe)
        pkgbuild = recipe / "PKGBUILD"
        source = pkgbuild.read_text()
        source = re.sub(
            r"^url=.*$",
            "url=" + repr((work / "upstream").as_uri()),
            source, count=1, flags=re.MULTILINE,
        )
        pkgbuild.write_text(source)
        with (output / "aur-build.log").open("w") as log:
            run(["makepkg", "--force", "--noconfirm"], recipe, stdout=log, stderr=subprocess.STDOUT)
        packages = list(recipe.glob("hypr-underlay-git-*.pkg.tar.zst"))
        if len(packages) != 1:
            raise RuntimeError(f"Expected one combined package, found {len(packages)}")
        artifact = output / packages[0].name
        shutil.copyfile(packages[0], artifact)
        listing = subprocess.check_output(["bsdtar", "-tf", str(artifact)], text=True)
        required = (
            "usr/bin/hypr-underlay",
            "usr/lib/hypr-underlay/hypr-underlay.so",
            "usr/share/hypr-underlay/omarchy-plugin/manifest.json",
            "usr/share/hypr-underlay/omarchy-plugin/omarchy/Underlay.qml",
            "usr/share/hypr-underlay/omarchy-plugin/hypr/shortcut.lua",
            "usr/share/hypr-underlay/omarchy-plugin/tools/hypr_underlay.py",
            "usr/share/licenses/hypr-underlay/LICENSE",
        )
        assert all(path in listing.splitlines() for path in required)
        assert not any(path.startswith(("home/", "root/", "etc/")) for path in listing.splitlines())
        assert "AGENTS.local.md" not in listing and ".git/" not in listing
        extraction = work / "extracted"
        extraction.mkdir()
        run(["bsdtar", "-xf", str(artifact), "-C", str(extraction)], work)
        runtime_files = [
            extraction / "usr/bin/hypr-underlay",
            extraction / "usr/share/hypr-underlay/omarchy-plugin/tools/hypr_underlay.py",
        ]
        for script in runtime_files:
            probe = (
                "import runpy; d=runpy.run_path(" + repr(str(script)) + "); "
                "print(d['PLUGIN']); print(d['COMPANION'])"
            )
            resolved = subprocess.check_output(["python3", "-c", probe], text=True).splitlines()
            assert Path(resolved[0]) == extraction / "usr/lib/hypr-underlay/hypr-underlay.so"
            assert Path(resolved[1]) == extraction / "usr/share/hypr-underlay/omarchy-plugin"
        run(["python3", "-m", "py_compile", str(extraction / "usr/bin/hypr-underlay")], work)
        print("PASS: makepkg built one combined package; payload, privacy and relocated runtime paths verified.")
        print("Package saved under build/; not installed or submitted.")


if __name__ == "__main__":
    main()
