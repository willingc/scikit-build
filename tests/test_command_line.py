#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""test_command_line
----------------------------------

Tests for various command line functionality.
"""

import os

from skbuild.utils import push_dir

from . import project_setup_py_test


@project_setup_py_test("hello", ["--help"])
def test_help(capsys):
    out, err = capsys.readouterr()
    assert "scikit-build options" not in out
    assert "Global options:" in out
    assert "usage:" in out


@project_setup_py_test("hello", ["--help-commands"])
def test_help_commands(capsys):
    out, err = capsys.readouterr()
    assert "scikit-build options" in out
    assert "--build-type" in out
    assert "Global options:" not in out
    assert "usage:" in out


@project_setup_py_test("hello", ["--author", "--name"])
def test_metadata_display(capsys):
    out, err = capsys.readouterr()
    assert "scikit-build options" not in out
    assert "Global options:" not in out
    assert "usage:" not in out
    assert "The scikit-build team" == out.splitlines()[0]
    assert "hello" == out.splitlines()[1]


def test_no_command():
    with push_dir():

        @project_setup_py_test("hello", [])
        def run():
            pass

        failed = False
        try:
            run()
        except SystemExit as e:
            failed = 'error: no commands supplied' in e.args[0]

        assert failed
        assert not os.path.exists('_skbuild')


def test_invalid_command():

    with push_dir():

        @project_setup_py_test("hello", ["unknown"])
        def run():
            pass

        failed = False
        try:
            run()
        except SystemExit as e:
            failed = 'error: invalid command' in e.args[0]

        assert failed
        assert not os.path.exists('_skbuild')


def test_too_many_separators():
    with push_dir():

        @project_setup_py_test("hello", ["--"] * 3)
        def run():
            pass

        failed = False
        try:
            run()
        except SystemExit as e:
            failed = e.args[0].startswith('ERROR: Too many')

        assert failed


@project_setup_py_test("hello",
                       ["build", "--", "-DMY_CMAKE_VARIABLE:BOOL=1"])
def test_cmake_args(capfd):
    out, err = capfd.readouterr()
    assert "Manually-specified variables were not used by the project" in err
    assert "MY_CMAKE_VARIABLE" in err
