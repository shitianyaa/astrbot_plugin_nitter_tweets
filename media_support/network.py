from urllib.request import urlopen as stdlib_urlopen


def compat_urlopen(request, timeout):
    return stdlib_urlopen(request, timeout=timeout)
