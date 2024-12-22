#!/bin/bash

# rustc-wrapper.sh

# 检查是否需要生成 llvm bitcode
if [[ "$@" != *"--emit=llvm-bc"* && "$@" != *"--emit=llvm-ir"* ]]; then
    set -- "$@" --emit=llvm-bc
fi

# 执行 rustc 编译
rustc "$@"

# # 获取编译的目标类型
# TARGET_TYPE=$(rustc --print target-libdir)
# 优先检查命令行中的 --crate-type 参数
if echo "$@" | grep -q -- "--crate-type=staticlib"; then
    CRATE_TYPE="staticlib"
else
    # 如果命令行没有提供 crate-type 参数，使用 cargo metadata 来检查
    CRATE_TYPE=$(cargo metadata --format-version 1 | jq -r '.packages[0].targets[] | select(.kind[] == "staticlib") | .kind[0]')
fi

# 判断是否是静态库目标类型
if [[ "$CRATE_TYPE" == *"staticlib"* ]]; then
    echo "Rust is compiling a static library, proceeding with bitcode embedding." >&2

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

            #添加 .llvm_bc 段
            for obj_file in *.o; do
                # 提取bc文件的名称，不包括扩展名
                bc_name=$(basename "$bc_path" .bc)
                # 检查obj_file是否包含bc_name
                if [[ "$obj_file" == "$bc_name"* ]]; then
                    echo "$bc_path" > "$TMP_FILE"
                    llvm-objcopy --add-section .llvm_bc="$TMP_FILE" "$obj_file"
                    echo "Bitcode path $bc_path added to $obj_file" >&2
                    break  # 找到匹配的文件后退出循环
                fi
            done

            # 重新打包 .a 文件
            llvm-ar rcs "$ar_file" *.o
            echo "Repacked staticlib: $ar_file with bitcode paths" >&2
        else
            echo "No matching .a file found for $bc_path" >&2
        fi
    done
else
    echo "Rust is not compiling a static library" >&2

    # 查找所有的 .bc 文件
    BC_FILES=($(find target/debug/deps -name "*.bc"))

    if [ ${#BC_FILES[@]} -eq 0 ]; then
        echo "No .bc files found. Exiting." >&2
        #exit 1
    fi

    # 临时文件保存所有 .bc 文件路径
    TMP_FILE=$(mktemp)

    for bc_file in "${BC_FILES[@]}"; do
        echo "$bc_file" >> "$TMP_FILE"
    done

    # 输出最终链接的 .bc 文件
    FINAL_BC="target/merged.bc"
    FINAL_LL="target/merged.ll"
    
    llvm-link $(cat "$TMP_FILE") -o "$FINAL_BC"
    llvm-dis "$FINAL_BC" > "$FINAL_LL"
    # 检查链接是否成功
    if [ -f "$FINAL_BC" ]; then
        echo "Successfully linked .bc files into $FINAL_BC" >&2
    else
        echo "Error: Linking failed. Exiting." >&2
        rm "$TMP_FILE"
       #exit 1
    fi

    # 清理临时文件
    rm "$TMP_FILE"
fi

echo "Script completed successfully.">&2
