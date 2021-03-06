import argparse
import glob
import itertools
import os
import os.path
import platform
import re
import subprocess
import shlex
import sys
import sysconfig

from subprocess import CalledProcessError

from .constants import (CMAKE_BUILD_DIR,
                        CMAKE_INSTALL_DIR,
                        SETUPTOOLS_INSTALL_DIR)
from .platform_specifics import get_platform
from .exceptions import SKBuildError

RE_FILE_INSTALL = re.compile(
    r"""[ \t]*file\(INSTALL DESTINATION "([^"]+)".*"([^"]+)"\).*""")


def pop_arg(arg, a, default=None):
    """Pops an arg(ument) from an argument list a and returns the new list
    and the value of the argument if present and a default otherwise.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(arg)
    ns, a = parser.parse_known_args(a)
    ns = tuple(vars(ns).items())
    if len(ns) > 0 and ns[0][1] is not None:
        val = ns[0][1]
    else:
        val = default
    return a, val


def _remove_cwd_prefix(path):
    cwd = os.getcwd()

    result = path.replace("/", os.sep)
    if result.startswith(cwd):
        result = os.path.relpath(result, cwd)

    if platform.system() == "Windows":
        result = result.replace("\\\\", os.sep)

    result = result.replace("\n", "")

    return result


class CMaker(object):

    def __init__(self):
        # verify that CMake is installed
        try:
            subprocess.check_call(['cmake', '--version'])
        except (OSError, CalledProcessError):
            raise SKBuildError(
                "Problem with the CMake installation, aborting build.")

        self.platform = get_platform()

    def configure(self, clargs=(), generator_id=None,
                  cmake_source_dir='.', cmake_install_dir=''):
        """Calls cmake to generate the Makefile/VS Solution/XCode project.

        Input:
        ------
        generator_id: string
            The string representing the CMake generator to use.
            If None, uses defaults for your platform.
        """

        # if no provided default generator_id, check environment
        if generator_id is None:
            generator_id = os.environ.get("CMAKE_GENERATOR")

        # if generator_id is provided on command line, use it
        clargs, cli_generator_id = pop_arg('-G', clargs)
        if cli_generator_id is not None:
            generator_id = cli_generator_id

        # use the generator_id returned from the platform, with the current
        # generator_id as a suggestion
        generator_id = self.platform.get_best_generator(generator_id)

        if generator_id is None:
            raise SKBuildError(
                "Could not get working generator for your system."
                "  Aborting build.")

        if not os.path.exists(CMAKE_BUILD_DIR):
            os.makedirs(CMAKE_BUILD_DIR)

        if not os.path.exists(CMAKE_INSTALL_DIR):
            os.makedirs(CMAKE_INSTALL_DIR)

        if not os.path.exists(SETUPTOOLS_INSTALL_DIR):
            os.makedirs(SETUPTOOLS_INSTALL_DIR)

        python_version = CMaker.get_python_version()
        python_include_dir = CMaker.get_python_include_dir(python_version)
        python_library = CMaker.get_python_library(python_version)

        cmake_source_dir = os.path.abspath(cmake_source_dir)
        cmd = [
            'cmake', cmake_source_dir, '-G', generator_id,
            ("-DCMAKE_INSTALL_PREFIX:PATH=" +
                os.path.abspath(
                    os.path.join(CMAKE_INSTALL_DIR, cmake_install_dir))),
            ("-DPYTHON_EXECUTABLE:FILEPATH=" +
                sys.executable),
            ("-DPYTHON_VERSION_STRING:STRING=" +
                sys.version.split(' ')[0]),
            ("-DPYTHON_INCLUDE_DIR:PATH=" +
                python_include_dir),
            ("-DPYTHON_LIBRARY:FILEPATH=" +
                python_library),
            ("-DSKBUILD:BOOL=" +
                "TRUE"),
            ("-DCMAKE_MODULE_PATH:PATH=" +
                os.path.join(os.path.dirname(__file__), "resources", "cmake"))
        ]

        cmd.extend(clargs)

        cmd.extend(
            filter(bool,
                   shlex.split(os.environ.get("SKBUILD_CONFIGURE_OPTIONS", "")))
        )

        # changes dir to cmake_build and calls cmake's configure step
        # to generate makefile
        rtn = subprocess.call(cmd, cwd=CMAKE_BUILD_DIR)
        if rtn != 0:
            raise SKBuildError(
                "An error occurred while configuring with CMake.\n"
                "  Command:\n"
                "    {}\n"
                "  Source directory:\n"
                "    {}\n"
                "  Working directory:\n"
                "    {}\n"
                "Please see CMake's output for more information.".format(
                    self._formatArgsForDisplay(cmd),
                    os.path.abspath(cmake_source_dir),
                    os.path.abspath(CMAKE_BUILD_DIR)))

        CMaker.check_for_bad_installs()

    @staticmethod
    def get_python_version():
        python_version = sysconfig.get_config_var('VERSION')

        if not python_version:
            python_version = sysconfig.get_config_var('py_version_short')

        if not python_version:
            python_version = ".".join(map(str, sys.version_info[:2]))

        return python_version

    # NOTE(opadron): The try-excepts raise the cyclomatic complexity, but we
    # need them for this function.
    @staticmethod  # noqa: C901
    def get_python_include_dir(python_version):
        # determine python include dir
        python_include_dir = sysconfig.get_config_var('INCLUDEPY')

        # if Python.h not found (or python_include_dir is None), try to find a
        # suitable include dir
        found_python_h = (
            python_include_dir is not None or
            os.path.exists(os.path.join(python_include_dir, 'Python.h'))
        )

        if not found_python_h:

            # NOTE(opadron): these possible prefixes must be guarded against
            # AttributeErrors and KeyErrors because they each can throw on
            # different platforms or even different builds on the same platform.
            include_py = sysconfig.get_config_var('INCLUDEPY')
            include_dir = sysconfig.get_config_var('INCLUDEDIR')
            include = None
            plat_include = None
            python_inc = None
            python_inc2 = None

            try:
                include = sysconfig.get_path('include')
            except (AttributeError, KeyError):
                pass

            try:
                plat_include = sysconfig.get_path('platinclude')
            except (AttributeError, KeyError):
                pass

            try:
                python_inc = sysconfig.get_python_inc()
            except AttributeError:
                pass

            if include_py is not None:
                include_py = os.path.dirname(include_py)
            if include is not None:
                include = os.path.dirname(include)
            if plat_include is not None:
                plat_include = os.path.dirname(plat_include)
            if python_inc is not None:
                python_inc2 = os.path.join(
                    python_inc, ".".join(map(str, sys.version_info[:2])))

            candidate_prefixes = list(filter(bool, (
                include_py,
                include_dir,
                include,
                plat_include,
                python_inc,
                python_inc2,
            )))

            candidate_versions = (python_version,)
            if python_version:
                candidate_versions += ('',)

            candidates = (
                os.path.join(prefix, ''.join(('python', ver)))
                for (prefix, ver) in itertools.product(
                    candidate_prefixes,
                    candidate_versions
                )
            )

            for candidate in candidates:
                if os.path.exists(os.path.join(candidate, 'Python.h')):
                    # we found an include directory
                    python_include_dir = candidate
                    break

        # TODO(opadron): what happens if we don't find an include directory?
        #                Throw SKBuildError?

        return python_include_dir

    @staticmethod
    def get_python_library(python_version):
        # determine direct path to libpython
        python_library = sysconfig.get_config_var('LIBRARY')

        # if static (or nonexistent), try to find a suitable dynamic libpython
        if (python_library is None or
                os.path.splitext(python_library)[1][-2:] == '.a'):

            candidate_lib_prefixes = ['', 'lib']

            candidate_extensions = ['.lib', '.so', '.a']
            if sysconfig.get_config_var('WITH_DYLD'):
                candidate_extensions.insert(0, '.dylib')

            candidate_versions = [python_version]
            if python_version:
                candidate_versions.append('')
                candidate_versions.insert(
                    0, "".join(python_version.split(".")[:2]))

            abiflags = getattr(sys, 'abiflags', '')
            candidate_abiflags = [abiflags]
            if abiflags:
                candidate_abiflags.append('')

            libdir = sysconfig.get_config_var('LIBDIR')
            if sysconfig.get_config_var('MULTIARCH'):
                masd = sysconfig.get_config_var('multiarchsubdir')
                if masd:
                    if masd.startswith(os.sep):
                        masd = masd[len(os.sep):]
                    libdir = os.path.join(libdir, masd)

            if libdir is None:
                libdir = os.path.abspath(os.path.join(
                    sysconfig.get_config_var('LIBDEST'), "..", "libs"))

            candidates = (
                os.path.join(
                    libdir,
                    ''.join((pre, 'python', ver, abi, ext))
                )
                for (pre, ext, ver, abi) in itertools.product(
                    candidate_lib_prefixes,
                    candidate_extensions,
                    candidate_versions,
                    candidate_abiflags
                )
            )

            for candidate in candidates:
                if os.path.exists(candidate):
                    # we found a (likely alternate) libpython
                    python_library = candidate
                    break

        # TODO(opadron): what happens if we don't find a libpython?

        return python_library

    @staticmethod
    def check_for_bad_installs():
        """This function tries to catch files that are meant to be installed
        outside the project root before they are actually installed.

        Indeed, we can not wait for the manifest, so we try to extract the
        information (install destination) from the CMake build files
        ``*.cmake`` found in ``CMAKE_BUILD_DIR``.

        It raises ``SKBuildError`` if it found install detination outside of
        ``CMAKE_INSTALL_DIR``.
        """

        bad_installs = []
        install_dir = os.path.join(os.getcwd(), CMAKE_INSTALL_DIR)

        for root, dir_list, file_list in os.walk(CMAKE_BUILD_DIR):
            for filename in file_list:
                if os.path.splitext(filename)[1] != ".cmake":
                    continue

                for line in open(os.path.join(root, filename)):
                    match = RE_FILE_INSTALL.match(line)
                    if match is None:
                        continue

                    destination = os.path.normpath(
                        match.group(1).replace("${CMAKE_INSTALL_PREFIX}",
                                               install_dir))

                    if not destination.startswith(install_dir):
                        bad_installs.append(
                            os.path.join(
                                destination,
                                os.path.basename(match.group(2))
                            )
                        )

        if bad_installs:
            raise SKBuildError("\n".join((
                "  CMake-installed files must be within the project root.",
                "    Project Root:",
                "      " + install_dir,
                "    Violating Files:",
                "\n".join(
                    ("      " + _install) for _install in bad_installs)
            )))

    def make(self, clargs=(), config="Release", source_dir="."):
        """Calls the system-specific make program to compile code.
        """
        clargs, config = pop_arg('--config', clargs, config)
        if not os.path.exists(CMAKE_BUILD_DIR):
            raise SKBuildError(("CMake build folder ({}) does not exist. "
                                "Did you forget to run configure before "
                                "make?").format(CMAKE_BUILD_DIR))

        cmd = ["cmake", "--build", source_dir,
               "--target", "install", "--config", config, "--"]
        cmd.extend(clargs)
        cmd.extend(
            filter(bool,
                   shlex.split(os.environ.get("SKBUILD_BUILD_OPTIONS", "")))
        )

        rtn = subprocess.call(cmd, cwd=CMAKE_BUILD_DIR)
        if rtn != 0:
            raise SKBuildError(
                "An error occurred while building with CMake.\n"
                "  Command:\n"
                "    {}\n"
                "  Source directory:\n"
                "    {}\n"
                "  Working directory:\n"
                "    {}\n"
                "Please see CMake's output for more information.".format(
                    self._formatArgsForDisplay(cmd),
                    os.path.abspath(source_dir),
                    os.path.abspath(CMAKE_BUILD_DIR)))

    def install(self):
        """Returns a list of file paths to install via setuptools that is
        compatible with the data_files keyword argument.
        """
        return self._parse_manifests()

    def _parse_manifests(self):
        paths = \
            glob.glob(os.path.join(CMAKE_BUILD_DIR, "install_manifest*.txt"))
        return [self._parse_manifest(path) for path in paths][0]

    def _parse_manifest(self, install_manifest_path):
        with open(install_manifest_path, "r") as manifest:
            return [_remove_cwd_prefix(path) for path in manifest]

        return []

    @staticmethod
    def _formatArgsForDisplay(args):
        """Format a list of arguments appropriately for display. When formatting
        a command and its arguments, the user should be able to execute the
        command by copying and pasting the output directly into a shell.

        Currently, the only formatting is naively surrounding each argument with
        quotation marks.
        """
        return ' '.join("\"{}\"".format(arg) for arg in args)
