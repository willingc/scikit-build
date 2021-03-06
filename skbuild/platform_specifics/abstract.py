
import os
import shutil
import subprocess

from ..utils import push_dir

test_folder = "_cmake_test_compile"


class CMakePlatform(object):

    def __init__(self):
        self._default_generators = list()

    @property
    def default_generators(self):
        return self._default_generators

    @default_generators.setter
    def default_generators(self, generators):
        self._default_generators = generators

    @staticmethod
    def write_test_cmakelist(languages):
        if not os.path.exists(test_folder):
            os.makedirs(test_folder)
        with open("{:s}/{:s}".format(test_folder, "CMakeLists.txt"), "w") as f:
            f.write("cmake_minimum_required(VERSION 2.8)\n")
            f.write("PROJECT(compiler_test NONE)\n")
            for language in languages:
                f.write("ENABLE_LANGUAGE({:s})\n".format(language))

    @staticmethod
    def cleanup_test():
        if os.path.exists(test_folder):
            shutil.rmtree(test_folder)

    def get_cmake_exe_path(self):
        """Override this method with additional logic where necessary
        if CMake is not on PATH.
        """
        return "cmake"

    # TODO: this method name is not great.  Does anyone have a better idea for
    # renaming it?
    def get_best_generator(
            self, generator=None, languages=("CXX", "C"), cleanup=True):
        """Loop over generators to find one that works.

        Parameters:
        generator: string or None
            If provided, uses only provided generator, instead of trying
            system defaults.
        languages: tuple
            the languages you'll need for your project, in terms that
            CMake recognizes.
        cleanup: bool
            If True, cleans up temporary folder used to test generators.
            Set to False for debugging to see CMake's output files.
        """

        candidate_generators = self.default_generators

        if generator is not None:
            candidate_generators = [generator]

        cmake_exe_path = self.get_cmake_exe_path()

        self.write_test_cmakelist(languages)

        working_generator = self.compile_test_cmakelist(
            cmake_exe_path, candidate_generators)

        if cleanup:
            CMakePlatform.cleanup_test()

        return working_generator

    @staticmethod
    @push_dir(directory=test_folder)
    def compile_test_cmakelist(cmake_exe_path, candidate_generators):

        # working generator is the first generator we find that works.
        working_generator = None

        # initial status is failure.  If subprocess call of cmake succeeds, it
        # gets set to 0.
        status = -1

        for generator in candidate_generators:
            # clear the cache for each attempted generator type
            if os.path.isdir('build'):
                shutil.rmtree('build')

            with push_dir('build', make_directory=True):
                # call cmake to see if the compiler specified by this
                # generator works for the specified languages
                cmake_execution_string = '{:s} ../ -G "{:s}"'.format(
                    cmake_exe_path, generator)
                status = subprocess.call(cmake_execution_string, shell=True)

            # cmake succeeded, this generator should work
            if status == 0:
                # we have a working generator, don't bother looking for more
                working_generator = generator
                break

        return working_generator
