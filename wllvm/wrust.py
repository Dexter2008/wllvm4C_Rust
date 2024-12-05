import os
import sys
import subprocess
import logging
from shutil import copyfile
from .compilers import attachBitcodePathToObject, elfSectionName
from .logconfig import logConfig

# Setup logger
_logger = logConfig(__name__)

def find_bitcode_files(target_dir="target/debug/deps"):
    """Find all .bc files in the target directory"""
    bc_files = []
    for root, dirs, files in os.walk(target_dir):
        for file in files:
            if file.endswith(".bc"):
                bc_files.append(os.path.join(root, file))
    return bc_files

def handle_staticlib(ar_file, bc_files):
    """Handle staticlib files (find .o files, embed .bc paths, and rebuild .a )"""
    # Extract .o files from the .a file (static library)
    subprocess.check_call(['llvm-ar', 'x', ar_file])

    # Add the .bc paths to each .o file
    for obj_file in os.listdir('.'):
        if obj_file.endswith('.o'):
            for bc_file in bc_files:
                _logger.debug(f"Attaching bitcode path {bc_file} to {obj_file}")
                # Call the attachBitcodePathToObject function from compilers
                attachBitcodePathToObject(bc_file, obj_file)

    # Repack .o files into the original .a file
    subprocess.check_call(['llvm-ar', 'rcs', ar_file] + [f for f in os.listdir('.') if f.endswith('.o')])
    _logger.info(f"Repacked staticlib: {ar_file} with bitcode paths")

    # Clean up .o files
    for obj_file in os.listdir('.'):
        if obj_file.endswith('.o'):
            os.remove(obj_file)

def handle_debug(bc_files):
    """Handle debug files (just log or perform other operations if needed)"""
    _logger.info("Handling debug target type. Bitcode files found:")
    for bc_file in bc_files:
        _logger.info(f"  - {bc_file}")
    # Perform any additional debug handling if necessary

def wrust():
    """Main entry point for wrust.py"""
    
    # 自动查找 target/debug/deps 下的 .bc 文件
    bc_files = find_bitcode_files()

    if not bc_files:
        _logger.error("No .bc files found in target directory.")
        sys.exit(1)

    _logger.info(f"Found {len(bc_files)} .bc files: {bc_files}")

    # 根据目标类型进行处理
    target_type = "staticlib"  # 默认假设为 staticlib

    # 自动获取目标类型（例如，检测 .a 文件来决定）
    ar_file = find_a_file_in_target()
    if ar_file:
        _logger.info(f"Detected staticlib: {ar_file}")
        handle_staticlib(ar_file, bc_files)
    else:
        _logger.warning("No staticlib (.a) file found, assuming debug target")
        handle_debug(bc_files)

def find_a_file_in_target(target_dir="target/debug"):
    """Find the staticlib (.a) file in target/debug"""
    for root, dirs, files in os.walk(target_dir):
        for file in files:
            if file.endswith(".a"):
                return os.path.join(root, file)
    return None

if __name__ == "__main__":
    main()
