#!/bin/bash

# 获取当前工作目录
WORK_DIR=$(pwd)

# 设置目标目录（根据实际情况修改）
TARGET_DIR="$WORK_DIR/target/debug/deps"

# 生成一个以目标文件名为键、源文件为值的映射
declare -A src_files_map

# 遍历 .rmeta 文件，构建 src 文件的依赖关系
for rmeta in "$TARGET_DIR"/*.rmeta; do
    # 获取 rmeta 文件名，不包含扩展名
    rmeta_basename=$(basename "$rmeta" .rmeta)

    # 使用 nm 或其他工具来解析 .rmeta 文件，提取出相关的源文件
    # 假设已经获取了源文件列表（这个部分可以根据实际情况来改写）
    src_files=$(grep -oP '(?<=src\/)[^ ]+' "$rmeta")  # 这个是一个示例，需要根据实际的 .rmeta 格式来提取

    for src_file in $src_files; do
        # 将每个源文件与其对应的 rmeta 文件关联起来
        src_files_map["$rmeta_basename"]="$src_file"
    done
done

# 找到需要链接的 .bc 文件并保存到一个列表中
bc_files=()
for bc in "$TARGET_DIR"/*.bc; do
    bc_basename=$(basename "$bc" .bc)

    # 查找每个 bc 文件对应的源文件
    if [[ -n "${src_files_map[$bc_basename]}" ]]; then
        bc_files+=("$bc")
    fi
done

# 创建一个临时链接文件夹
LINK_DIR="$WORK_DIR/linked_bc_files"
mkdir -p "$LINK_DIR"

# 链接找到的所有 .bc 文件
for bc in "${bc_files[@]}"; do
    ln -sf "$bc" "$LINK_DIR/$(basename "$bc")"
done

echo "所有 .bc 文件已链接完成"

# 创建链接命令并执行
LIBRARY_OUTPUT="$WORK_DIR/output.a"
llvm-ar rcs "$LIBRARY_OUTPUT" "$LINK_DIR"/*.bc

echo "静态库已生成：$LIBRARY_OUTPUT"
