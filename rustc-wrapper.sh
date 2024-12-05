#!/bin/bash

# rustc-wrapper.sh

if [[ "$@" != *"--emit=llvm-bc"* && "$@" != *"--emit=llvm-ir"* ]]; then
    set -- "$@" --emit=llvm-bc
fi

rustc "$@"

# 查找所有生成的 .bc 文件
BC_FILES=($(find target/debug/deps -name "*.bc" | head -n 100)) # 假设最多查找100个文件
TMP_FILE=/tmp/tmpfile.txt
# 存储 .bc 文件路径的数组
declare -a bc_paths

# 将 .bc 文件路径添加到数组中
for bc_file in "${BC_FILES[@]}"; do
    bc_paths+=("$bc_file")
done

# 遍历 .bc 文件数组
for bc_path in "${bc_paths[@]}"; do
    # 提取文件名，用于查找同名的 .a 文件
    filename="lib$(basename "$bc_path" .bc).a"

    # 查找同名的 .a 文件
    ar_file=$(find target/debug -name "$filename" | head -n 1)

    if [[ -f "$ar_file" ]]; then
        echo "Found staticlib: $ar_file" >&2

        # 提取 .a 文件中的所有 .o 文件
        llvm-ar x "$ar_file"

        # 查找同名的 .o 文件，并添加 .llvm_bc 段
        for obj_file in *.o; do
            # if [[ "$obj_file" == *"$filename"* ]]; then
            echo $bc_path > $TMP_FILE
            llvm-objcopy --add-section .llvm_bc="$TMP_FILE" "$obj_file"
            echo "Bitcode path $bc_path added to $obj_file" >&2
            # fi
        done

        # 重新打包 .a 文件
        llvm-ar rcs "$ar_file" *.o
        echo "Repacked staticlib: $ar_file with bitcode paths" >&2
    else
        echo "No matching .a file found for $bc_path" >&2
    fi
done
# BC_PATH=$(find target/debug/deps -name "*.bc" | head -n 1)
# TMP_FILE=/tmp/tmpfile.txt
# echo $BC_PATH > $TMP_FILE

# if [[ "$@" == *"staticlib"* ]]; then
#     AR_FILE=$(find target/debug -name "*.a" | head -n 1)  # 查找生成的 .a 文件
#     echo "Found staticlib: $AR_FILE">&2

#     llvm-ar x "$AR_FILE"  # 提取 .a 文件中的所有 .o 文件

#     for obj_file in *.o; do
#         llvm-objcopy --add-section .llvm_bc="$TMP_FILE" "$obj_file"
#         echo "Bitcode path $BC_PATH added to $obj_file">&2
#         # break
#     done

#     llvm-ar rcs "$AR_FILE" *.o
#     echo "Repacked staticlib: $AR_FILE with bitcode paths">&2
# else
#     OBJ_FILE=$(echo "$BC_PATH" | sed 's/\.bc$/.o/')
#     llvm-objcopy --add-section .llvm_bc="$TMP_FILE" "$OBJ_FILE"
#     echo "Bitcode path $BC_PATH added to $OBJ_FILE">&2
# fi