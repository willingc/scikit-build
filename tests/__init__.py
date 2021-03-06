# -*- coding: utf-8 -*-

import _pytest.tmpdir
import os
import os.path
import py.path
import re
import six
import subprocess
import sys


from contextlib import contextmanager

from skbuild.utils import push_dir


SAMPLES_DIR = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    'samples',
    )


@contextmanager
def push_argv(argv):
    old_argv = sys.argv
    sys.argv = argv
    yield
    sys.argv = old_argv


@contextmanager
def push_env(**kwargs):
    """This context manager allow to set/unset environment variables.
    """
    saved_env = dict(os.environ)
    for var, value in kwargs.items():
        if value is not None:
            os.environ[var] = value
        elif var in os.environ:
            del os.environ[var]
    yield
    os.environ.clear()
    for (saved_var, saved_value) in saved_env.items():
        os.environ[saved_var] = saved_value


def _tmpdir(basename):
    """This function returns a temporary directory similar to the one
    returned by the ``tmpdir`` pytest fixture.
    The difference is that the `basetemp` is not configurable using
    the pytest settings."""

    # Adapted from _pytest.tmpdir.tmpdir()
    basename = re.sub("[\W]", "_", basename)
    max_val = 30
    if len(basename) > max_val:
        basename = basename[:max_val]

    # Adapted from _pytest.tmpdir.TempdirFactory.getbasetemp()
    try:
        basetemp = _tmpdir._basetemp
    except AttributeError:
        temproot = py.path.local.get_temproot()
        user = _pytest.tmpdir.get_user()

        if user:
            # use a sub-directory in the temproot to speed-up
            # make_numbered_dir() call
            rootdir = temproot.join('pytest-of-%s' % user)
        else:
            rootdir = temproot

        rootdir.ensure(dir=1)
        basetemp = py.path.local.make_numbered_dir(prefix='pytest-',
                                                   rootdir=rootdir)

    # Adapted from _pytest.tmpdir.TempdirFactory.mktemp
    return py.path.local.make_numbered_dir(prefix=basename,
                                           keep=0, rootdir=basetemp,
                                           lock_timeout=None)


def _copy_dir(target_dir, entry, on_duplicate='exception', keep_top_dir=False):

    if isinstance(entry, six.string_types):
        entry = py.path.local(entry)

    # Copied from pytest-datafiles/pytest_datafiles.py (MIT License)
    basename = entry.basename
    if keep_top_dir:
        if on_duplicate == 'overwrite' or not (target_dir / basename).exists():
            entry.copy(target_dir / basename)
        elif on_duplicate == 'exception':
            raise ValueError(
                "'%s' already exists (entry %s)" % (basename, entry)
                )
        # else: on_duplicate == 'ignore': do nothing with entry
    else:
        # Regular directory (no keep_top_dir). Need to check every file
        # for duplicates
        if on_duplicate == 'overwrite':
            entry.copy(target_dir)
            return
        for sub_entry in entry.listdir():
            if not (target_dir / sub_entry.basename).exists():
                sub_entry.copy(target_dir / sub_entry.basename)
                continue
            if on_duplicate == 'exception':
                # target exists
                raise ValueError(
                    "'%s' already exists (entry %s)" % (
                        (target_dir / sub_entry.basename),
                        sub_entry,
                        )
                    )
            # on_duplicate == 'ignore': do nothing with e2


def initialize_git_repo_and_commit(project_dir):
    """Convenience function creating a git repository in ``project_dir``.

    If ``project_dir`` does NOT contain a ``.git`` directory, a new
    git repository with one commit containing all the directories and files
    is created.
    """
    if project_dir.join('.git').exists():
        return

    with push_dir(str(project_dir)):
        for cmd in [
            ['git', 'init'],
            ['git', 'config', 'user.name', 'scikit-build'],
            ['git', 'config', 'user.email', 'test@test'],
            ['git', 'add', '-A'],
            ['git', 'commit', '-m', 'Initial commit']
        ]:
            subprocess.check_call(cmd)


def prepare_project(project, tmp_project_dir):
    """Convenience function setting up the build directory ``tmp_project_dir``
    for the selected sample ``project``.

    If ``tmp_project_dir`` does not exist, it is created.

    If ``tmp_project_dir`` is empty, the sample ``project`` is copied into it.
    """

    tmp_project_dir = py.path.local(tmp_project_dir)

    # Create project directory if it does not exist
    if not tmp_project_dir.exists():
        tmp_project_dir = _tmpdir(project)

    # If empty, copy project files and initialize git
    if not tmp_project_dir.listdir():
        _copy_dir(tmp_project_dir, os.path.join(SAMPLES_DIR, project))


@contextmanager
def execute_setup_py(project_dir, setup_args):
    """Context manager executing ``setup.py`` with the given arguments.

    It yields after changing the current working directory
    to ``project_dir``.
    """

    with push_dir(str(project_dir)), \
            push_argv(["setup.py"] + setup_args):
        setup_code = None

        with open("setup.py", "r") as fp:
            setup_code = compile(fp.read(), "setup.py", mode="exec")

        if setup_code is not None:
            six.exec_(setup_code)

        yield


def project_setup_py_test(project, setup_args, tmp_dir=None):

    def dec(fun):

        @six.wraps(fun)
        def wrapped(*iargs, **ikwargs):

            if wrapped.tmp_dir is None:
                wrapped.tmp_dir = _tmpdir(fun.__name__)
                prepare_project(wrapped.project, wrapped.tmp_dir)
                initialize_git_repo_and_commit(wrapped.tmp_dir)

            with execute_setup_py(wrapped.tmp_dir, wrapped.setup_args):
                result2 = fun(*iargs, **ikwargs)

            return wrapped.tmp_dir, result2

        wrapped.project = project
        wrapped.setup_args = setup_args
        wrapped.tmp_dir = tmp_dir

        return wrapped

    return dec
