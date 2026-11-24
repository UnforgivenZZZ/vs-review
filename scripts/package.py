#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def runtime_files() -> list[Path]:
    files = [ROOT / name for name in ("package.json", "README.md", "LICENSE", "pyproject.toml", "uv.lock")]
    files.extend((ROOT / "vscode").glob("*.js"))
    files.extend(path for path in (ROOT / "src/pair_review").rglob("*") if path.is_file() and "__pycache__" not in path.parts)
    return sorted(files)


def manifest(package: dict) -> str:
    properties = "".join(
        f'<Property Id="{key}" Value="{escape(value)}"/>'
        for key, value in (
            ("Microsoft.VisualStudio.Code.Engine", package["engines"]["vscode"]),
            ("Microsoft.VisualStudio.Code.ExtensionKind", "workspace"),
            ("Microsoft.VisualStudio.Code.ExecutesCode", "true"),
        )
    )
    return f'''<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="{escape(package['name'])}" Version="{escape(package['version'])}" Publisher="{escape(package['publisher'])}"/>
    <DisplayName>{escape(package['displayName'])}</DisplayName>
    <Description xml:space="preserve">{escape(package['description'])}</Description>
    <Tags>review,agent,diff,mcp,python</Tags>
    <Categories>Other</Categories>
    <GalleryFlags>Public</GalleryFlags>
    <Properties>{properties}</Properties>
    <License>extension/LICENSE</License>
  </Metadata>
  <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/>
    <Asset Type="Microsoft.VisualStudio.Services.Content.Details" Path="extension/README.md" Addressable="true"/>
    <Asset Type="Microsoft.VisualStudio.Services.Content.License" Path="extension/LICENSE" Addressable="true"/>
  </Assets>
</PackageManifest>'''


def content_types() -> str:
    defaults = {
        "json": "application/json",
        "js": "application/javascript",
        "md": "text/markdown",
        "css": "text/css",
        "py": "text/plain",
        "toml": "text/plain",
        "lock": "text/plain",
        "vsixmanifest": "text/xml",
    }
    entries = "".join(f'<Default Extension="{name}" ContentType="{kind}"/>' for name, kind in defaults.items())
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        + entries
        + '<Override PartName="/extension/LICENSE" ContentType="text/plain"/></Types>'
    )


def main() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    output = DIST / f"{package['name']}-{package['version']}.vsix"
    DIST.mkdir(exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("extension.vsixmanifest", manifest(package))
        archive.writestr("[Content_Types].xml", content_types())
        for file in runtime_files():
            if not file.is_file() or file.is_symlink():
                raise RuntimeError(f"Invalid package input: {file}")
            archive.write(file, "extension/" + file.relative_to(ROOT).as_posix())
    print(output)


if __name__ == "__main__":
    main()
