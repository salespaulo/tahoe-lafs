"""
Produce reports about the versions of Python software in use by Tahoe-LAFS
for debugging and auditing purposes.

Ported to Python 3.
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from future.utils import PY2
if PY2:
    from builtins import filter, map, zip, ascii, chr, hex, input, next, oct, open, pow, round, super, bytes, dict, int, list, object, range, str, max, min  # noqa: F401

__all__ = [
    "PackagingError",
    "get_package_versions",
    "get_package_versions_string",
    "normalized_version",
]

import os, platform, re, sys, traceback, pkg_resources

import six

import distro

from . import (
    __appname__,
    full_version,
    branch,
)
from .util import (
    verlib,
)

if getattr(sys, 'frozen', None):
    # "Frozen" python interpreters (i.e., standalone executables
    # generated by PyInstaller and other, similar utilities) run
    # independently of a traditional setuptools-based packaging
    # environment, and so pkg_resources.get_distribution() cannot be
    # used in such cases to gather a list of requirements at runtime
    # (and because a frozen application is one that has already been
    # "installed", an empty list suffices here).
    _INSTALL_REQUIRES = []
else:
    _INSTALL_REQUIRES = list(
        str(req)
        for req
        in pkg_resources.get_distribution(__appname__).requires()
    )

class PackagingError(EnvironmentError):
    """
    Raised when there is an error in packaging of Tahoe-LAFS or its
    dependencies which makes it impossible to proceed safely.
    """

def get_package_versions():
    return dict([(k, v) for k, (v, l, c) in _vers_and_locs_list])

def get_package_versions_string(show_paths=False, debug=False):
    res = []
    for p, (v, loc, comment) in _vers_and_locs_list:
        info = str(p) + ": " + str(v)
        if comment:
            info = info + " [%s]" % str(comment)
        if show_paths:
            info = info + " (%s)" % str(loc)
        res.append(info)

    output = "\n".join(res) + "\n"

    if _cross_check_errors:
        output += _get_error_string(_cross_check_errors, debug=debug)

    return output

_distributor_id_cmdline_re = re.compile("(?:Distributor ID:)\s*(.*)", re.I)
_release_cmdline_re = re.compile("(?:Release:)\s*(.*)", re.I)

_distributor_id_file_re = re.compile("(?:DISTRIB_ID\s*=)\s*(.*)", re.I)
_release_file_re = re.compile("(?:DISTRIB_RELEASE\s*=)\s*(.*)", re.I)

_distname = None
_version = None

def normalized_version(verstr, what=None):
    try:
        suggested = verlib.suggest_normalized_version(verstr) or verstr
        return verlib.NormalizedVersion(suggested)
    except verlib.IrrationalVersionError:
        raise
    except Exception:
        cls, value, trace = sys.exc_info()
        new_exc = PackagingError("could not parse %s due to %s: %s"
                                 % (what or repr(verstr), cls.__name__, value))
        six.reraise(cls, new_exc, trace)

def _get_error_string(errors, debug=False):

    msg = "\n%s\n" % ("\n".join(errors),)
    if debug:
        msg += (
            "\n"
            "For debugging purposes, the PYTHONPATH was\n"
            "  %r\n"
            "install_requires was\n"
            "  %r\n"
            "sys.path after importing pkg_resources was\n"
            "  %s\n"
            % (
                os.environ.get('PYTHONPATH'),
                _INSTALL_REQUIRES,
                (os.pathsep+"\n  ").join(sys.path),
            )
        )
    return msg

def _cross_check(pkg_resources_vers_and_locs, imported_vers_and_locs_list):
    """This function returns a list of errors due to any failed cross-checks."""

    from ._auto_deps import not_import_versionable

    errors = []
    not_pkg_resourceable = ['python', 'platform', __appname__.lower(), 'openssl']

    for name, (imp_ver, imp_loc, imp_comment) in imported_vers_and_locs_list:
        name = name.lower()
        if name not in not_pkg_resourceable:
            if name not in pkg_resources_vers_and_locs:
                if name == "setuptools" and "distribute" in pkg_resources_vers_and_locs:
                    pr_ver, pr_loc = pkg_resources_vers_and_locs["distribute"]
                    if not (os.path.normpath(os.path.realpath(pr_loc)) == os.path.normpath(os.path.realpath(imp_loc))
                            and imp_comment == "distribute"):
                        errors.append("Warning: dependency 'setuptools' found to be version %r of 'distribute' from %r "
                                      "by pkg_resources, but 'import setuptools' gave version %r [%s] from %r. "
                                      "A version mismatch is expected, but a location mismatch is not."
                                      % (pr_ver, pr_loc, imp_ver, imp_comment or 'probably *not* distribute', imp_loc))
                else:
                    errors.append("Warning: dependency %r (version %r imported from %r) was not found by pkg_resources."
                                  % (name, imp_ver, imp_loc))
                continue

            pr_ver, pr_loc = pkg_resources_vers_and_locs[name]
            if imp_ver is None and imp_loc is None:
                errors.append("Warning: dependency %r could not be imported. pkg_resources thought it should be possible "
                              "to import version %r from %r.\nThe exception trace was %r."
                              % (name, pr_ver, pr_loc, imp_comment))
                continue

            # If the pkg_resources version is identical to the imported version, don't attempt
            # to normalize them, since it is unnecessary and may fail (ticket #2499).
            if imp_ver != 'unknown' and pr_ver == imp_ver:
                continue

            try:
                pr_normver = normalized_version(pr_ver)
            except verlib.IrrationalVersionError:
                continue
            except Exception as e:
                errors.append("Warning: version number %r found for dependency %r by pkg_resources could not be parsed. "
                              "The version found by import was %r from %r. "
                              "pkg_resources thought it should be found at %r. "
                              "The exception was %s: %s"
                              % (pr_ver, name, imp_ver, imp_loc, pr_loc, e.__class__.__name__, e))
            else:
                if imp_ver == 'unknown':
                    if name not in not_import_versionable:
                        errors.append("Warning: unexpectedly could not find a version number for dependency %r imported from %r. "
                                      "pkg_resources thought it should be version %r at %r."
                                      % (name, imp_loc, pr_ver, pr_loc))
                else:
                    try:
                        imp_normver = normalized_version(imp_ver)
                    except verlib.IrrationalVersionError:
                        continue
                    except Exception as e:
                        errors.append("Warning: version number %r found for dependency %r (imported from %r) could not be parsed. "
                                      "pkg_resources thought it should be version %r at %r. "
                                      "The exception was %s: %s"
                                      % (imp_ver, name, imp_loc, pr_ver, pr_loc, e.__class__.__name__, e))
                    else:
                        if pr_ver == 'unknown' or (pr_normver != imp_normver):
                            if not os.path.normpath(os.path.realpath(pr_loc)) == os.path.normpath(os.path.realpath(imp_loc)):
                                errors.append("Warning: dependency %r found to have version number %r (normalized to %r, from %r) "
                                              "by pkg_resources, but version %r (normalized to %r, from %r) by import."
                                              % (name, pr_ver, str(pr_normver), pr_loc, imp_ver, str(imp_normver), imp_loc))

    return errors

def _get_openssl_version():
    try:
        from OpenSSL import SSL
        return _extract_openssl_version(SSL)
    except Exception:
        return ("unknown", None, None)

def _extract_openssl_version(ssl_module):
    openssl_version = ssl_module.SSLeay_version(ssl_module.SSLEAY_VERSION)
    if openssl_version.startswith('OpenSSL '):
        openssl_version = openssl_version[8 :]

    (version, _, comment) = openssl_version.partition(' ')

    try:
        openssl_cflags = ssl_module.SSLeay_version(ssl_module.SSLEAY_CFLAGS)
        if '-DOPENSSL_NO_HEARTBEATS' in openssl_cflags.split(' '):
            comment += ", no heartbeats"
    except Exception:
        pass

    return (version, None, comment if comment else None)


def _get_platform():
    # Our version of platform.platform(), telling us both less and more than the
    # Python Standard Library's version does.
    # We omit details such as the Linux kernel version number, but we add a
    # more detailed and correct rendition of the Linux distribution and
    # distribution-version.
    if "linux" in platform.system().lower():
        return (
            platform.system() + "-" +
            "_".join(distro.linux_distribution()[:2]) + "-" +
            platform.machine() + "-" +
            "_".join([x for x in platform.architecture() if x])
        )
    else:
        return platform.platform()

def _get_package_versions_and_locations():
    import warnings
    from ._auto_deps import package_imports, global_deprecation_messages, deprecation_messages, \
        runtime_warning_messages, warning_imports, ignorable

    def package_dir(srcfile):
        return os.path.dirname(os.path.dirname(os.path.normcase(os.path.realpath(srcfile))))

    # pkg_resources.require returns the distribution that pkg_resources attempted to put
    # on sys.path, which can differ from the one that we actually import due to #1258,
    # or any other bug that causes sys.path to be set up incorrectly. Therefore we
    # must import the packages in order to check their versions and paths.

    # This is to suppress all UserWarnings and various DeprecationWarnings and RuntimeWarnings
    # (listed in _auto_deps.py).

    warnings.filterwarnings("ignore", category=UserWarning, append=True)

    for msg in global_deprecation_messages + deprecation_messages:
        warnings.filterwarnings("ignore", category=DeprecationWarning, message=msg, append=True)
    for msg in runtime_warning_messages:
        warnings.filterwarnings("ignore", category=RuntimeWarning, message=msg, append=True)
    try:
        for modulename in warning_imports:
            try:
                __import__(modulename)
            except (ImportError, SyntaxError):
                pass
    finally:
        # Leave suppressions for UserWarnings and global_deprecation_messages active.
        for _ in runtime_warning_messages + deprecation_messages:
            warnings.filters.pop()

    packages = []
    pkg_resources_vers_and_locs = dict()

    if not hasattr(sys, 'frozen'):
        pkg_resources_vers_and_locs = {
            p.project_name.lower(): (str(p.version), p.location)
            for p
            in pkg_resources.require(_INSTALL_REQUIRES)
        }

    def get_version(module):
        if hasattr(module, '__version__'):
            return str(getattr(module, '__version__'))
        elif hasattr(module, 'version'):
            ver = getattr(module, 'version')
            if isinstance(ver, tuple):
                return '.'.join(map(str, ver))
            else:
                return str(ver)
        else:
            return 'unknown'

    for pkgname, modulename in [(__appname__, 'allmydata')] + package_imports:
        if modulename:
            try:
                __import__(modulename)
                module = sys.modules[modulename]
            except (ImportError, SyntaxError):
                etype, emsg, etrace = sys.exc_info()
                trace_info = (etype, str(emsg), ([None] + traceback.extract_tb(etrace))[-1])
                packages.append( (pkgname, (None, None, trace_info)) )
            else:
                comment = None
                if pkgname == __appname__:
                    comment = "%s: %s" % (branch, full_version)
                elif pkgname == 'setuptools' and hasattr(module, '_distribute'):
                    # distribute does not report its version in any module variables
                    comment = 'distribute'
                ver = get_version(module)
                loc = package_dir(module.__file__)
                if ver == "unknown" and pkgname in pkg_resources_vers_and_locs:
                    (pr_ver, pr_loc) = pkg_resources_vers_and_locs[pkgname]
                    if loc == os.path.normcase(os.path.realpath(pr_loc)):
                        ver = pr_ver
                packages.append( (pkgname, (ver, loc, comment)) )
        elif pkgname == 'python':
            packages.append( (pkgname, (platform.python_version(), sys.executable, None)) )
        elif pkgname == 'platform':
            packages.append( (pkgname, (_get_platform(), None, None)) )
        elif pkgname == 'OpenSSL':
            packages.append( (pkgname, _get_openssl_version()) )

    cross_check_errors = []

    if len(pkg_resources_vers_and_locs) > 0:
        imported_packages = set([p.lower() for (p, _) in packages])
        extra_packages = []

        for pr_name, (pr_ver, pr_loc) in pkg_resources_vers_and_locs.items():
            if pr_name not in imported_packages and pr_name not in ignorable:
                extra_packages.append( (pr_name, (pr_ver, pr_loc, "according to pkg_resources")) )

        cross_check_errors = _cross_check(pkg_resources_vers_and_locs, packages)
        packages += extra_packages

    return packages, cross_check_errors


_vers_and_locs_list, _cross_check_errors = _get_package_versions_and_locations()
