from __future__ import annotations

import sys
from urllib.request import urlopen as stdlib_urlopen


def compat_urlopen(request, timeout):
    for module_name in _compat_media_module_names():
        media_module = sys.modules.get(module_name)
        patched_urlopen = getattr(media_module, "urlopen", None)
        if callable(patched_urlopen) and patched_urlopen is not stdlib_urlopen:
            return patched_urlopen(request, timeout)
    return stdlib_urlopen(request, timeout=timeout)


def _compat_media_module_names() -> tuple[str, ...]:
    names = ["media"]
    package = __package__ or ""
    if "." in package:
        root_package = package.rsplit(".", 1)[0]
        names.append(f"{root_package}.media")
    return tuple(dict.fromkeys(names))
