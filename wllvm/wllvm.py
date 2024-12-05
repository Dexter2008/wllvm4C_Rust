#!/usr/bin/env python
"""This is a wrapper around the real compiler.

It first invokes a real compiler to generate
an object file.  Then it invokes a bitcode
compiler to generate a parallel bitcode file.
It records the location of the bitcode in an
ELF section of the object file so that it can be
found later after all of the objects are
linked into a library or executable.
"""

import sys
from .arglistfilter import ArgumentListFilter
from .compilers import wcompile, compile_rust_to_bc, link_bitcode_files
from .wrust import wrust
def main():
    """ The entry point to wllvm. """
    # af = ArgumentListFilter(sys.argv[1:])

    # # 编译 Rust 文件到 bitcode
    # for rust_file in af.rustFiles:
    #     rust_bc_file = rust_file + '.bc'
    #     compile_rust_to_bc(rust_file, rust_bc_file)
    # wrust()
    return wcompile("wllvm") 

    # 获取用户指定的输出文件名
    # output_bc_file = af.getOutputFilename()

    # # 链接所有的 bitcode 文件
    # all_bc_files = af.rustFiles + af.inputFiles
    # link_bitcode_files(all_bc_files, output_bc_file)

    # print(f"Linked bitcode file created: {output_bc_file}")
    # return 0


if __name__ == '__main__':
    sys.exit(main())
